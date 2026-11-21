"""
JSON extraction and enforcement for LLM responses.

When a phase expects JSON, the LLM sometimes returns markdown prose with JSON
embedded inside code fences or surrounding commentary. This module extracts,
validates, and parses JSON from LLM responses deterministically — without
retrying the full LLM call.

Public API
----------
    extract_first_json(text, expect) -> Any
    extract_json(text) -> str
    parse_llm_json(text, fallback) -> Any
    enforce_json_keys(data, required_keys, phase) -> dict
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Tuple

logger = logging.getLogger(__name__)


_DECODER = json.JSONDecoder()
_JSON_START_RE = re.compile(r"[\[{]")


def _find_first_json(text: str, expect: Any) -> Tuple[Any, str]:
    """Locate the first complete top-level JSON value of type *expect* in *text*.

    Returns (value, source text of value). Raises ValueError when there is none.
    """
    if not isinstance(text, str):
        raise ValueError(f"model output is {type(text).__name__}, not text")
    stripped = text.strip()
    # Some models double-encode: the whole reply is a JSON string holding the JSON.
    if stripped.startswith('"'):
        try:
            inner = json.loads(stripped)
        except json.JSONDecodeError as e:
            logger.debug("json_enforcer: reply starts with a quote but is not a JSON string: %s", e)
        else:
            if isinstance(inner, str):
                return _find_first_json(inner, expect)
    pos = 0
    while True:
        m = _JSON_START_RE.search(text, pos)
        if m is None:
            break
        start = m.start()
        try:
            value, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError as e:
            # Ran off the end: a truncated value. Everything after `start` is inside it, so any
            # later match would be a nested fragment of it, never the answer.
            if e.pos >= len(text.rstrip()) or e.msg.startswith("Unterminated string"):
                break
            # Skip past the broken span so a nested fragment of it is not taken for the answer.
            pos = max(start + 1, e.pos)
            continue
        if isinstance(value, expect):
            return value, text[start:end]
        # A complete value of the wrong type (e.g. a list when an object is wanted): skip all
        # of it, so one of its elements is not returned as if it were the top-level answer.
        pos = end
    raise ValueError("no complete JSON value found in model output")


def extract_first_json(text: str, expect: Any = (dict, list)) -> Any:
    """Parse the FIRST complete top-level JSON value out of an LLM reply.

    Real models wrap JSON in prose and code fences and often keep talking after it
    ("{...}\n\nExplanation: ..." or a second object). json.loads on the whole reply then
    fails with "Extra data", and greedy first-{-to-last-} regexes swallow the trailing text.
    This scans for the first `{`/`[` that json.JSONDecoder.raw_decode can decode completely
    and ignores whatever follows it.

    Parameters
    ----------
    text:
        Raw LLM reply.
    expect:
        Type (or tuple of types) the value must be; values of other types are skipped whole.

    Raises
    ------
    ValueError
        No complete JSON value of the expected type was found.
    """
    return _find_first_json(text, expect)[0]


def extract_json(text: str) -> str:
    """Return the text of the first complete JSON object/array in an LLM reply.

    Falls back to the original (stripped) text when none is found; callers that then
    json.loads it must handle JSONDecodeError.
    """
    try:
        return _find_first_json(text, (dict, list))[1]
    except ValueError as e:
        logger.warning(
            "json_enforcer: could not extract valid JSON from LLM response (len=%d): %s",
            len(text or ""), e,
        )
        return (text or "").strip()


def parse_llm_json(text: str, fallback: Any = None) -> Any:
    """Extract and parse JSON from an LLM response. Returns fallback on failure.

    Parameters
    ----------
    text:
        Raw LLM response, potentially containing prose + embedded JSON.
    fallback:
        Value returned when extraction or parsing fails (default: None).

    Returns
    -------
    Any
        Parsed Python object (dict, list, etc.) or *fallback* on failure.
    """
    extracted = extract_json(text)
    try:
        return json.loads(extracted)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("json_enforcer: parse failed after extraction: %s", e)
        return fallback


def enforce_json_keys(
    data: dict,
    required_keys: list[str],
    phase: str = "unknown",
) -> dict:
    """Validate that required keys are present in a parsed JSON dict.

    Does NOT raise — missing keys are logged as warnings so that callers can
    apply their own fallback logic. This is intentional: a missing key from
    the LLM should trigger a deterministic fallback, not crash the pipeline.

    Parameters
    ----------
    data:
        Parsed JSON dict from the LLM response.
    required_keys:
        List of key names that must be present.
    phase:
        Phase name for context in log messages.

    Returns
    -------
    dict
        The same *data* dict (mutations are visible to the caller).
    """
    missing = [k for k in required_keys if k not in data]
    if missing:
        logger.warning(
            "json_enforcer [%s]: missing required keys: %s", phase, missing
        )
    return data
