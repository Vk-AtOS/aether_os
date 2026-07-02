"""
JSON extraction and enforcement for LLM responses.

When a phase expects JSON, the LLM sometimes returns markdown prose with JSON
embedded inside code fences or surrounding commentary. This module extracts,
validates, and parses JSON from LLM responses deterministically — without
retrying the full LLM call.

Public API
----------
    extract_json(text) -> str
    parse_llm_json(text, fallback) -> Any
    enforce_json_keys(data, required_keys, phase) -> dict
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_json(text: str) -> str:
    """Extract JSON from LLM response that may contain markdown or prose.

    Priority order:
    1. Response is already valid JSON → return as-is
    2. ```json ... ``` code block → extract and return
    3. ``` ... ``` code block (any language) → extract and return
    4. First { to last } or first [ to last ] → extract and return
    5. Return original text (caller handles parse error)

    Parameters
    ----------
    text:
        Raw LLM response string, possibly containing markdown prose, code
        fences, or embedded JSON.

    Returns
    -------
    str
        The best JSON candidate extracted from text. May still be invalid JSON
        if all extraction strategies fail — callers should catch JSONDecodeError.
    """
    text = text.strip()

    # ── 1. Already valid JSON ─────────────────────────────────────────────────
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # ── 2. ```json ... ``` block ──────────────────────────────────────────────
    m = re.search(r'```json\s*([\s\S]*?)```', text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # ── 3. Any ``` block (language tag optional) ──────────────────────────────
    m = re.search(r'```(?:\w+)?\s*([\s\S]*?)```', text)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # ── 4. Greedy brace/bracket extraction ───────────────────────────────────
    # Try object first (most common), then array.
    for pattern in (r'\{[\s\S]*\}', r'\[[\s\S]*\]'):
        m = re.search(pattern, text)
        if m:
            candidate = m.group(0)
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

    # ── 5. Give up — return original and let the caller handle the error ──────
    logger.warning(
        "json_enforcer: could not extract valid JSON from LLM response (len=%d)", len(text)
    )
    return text


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
