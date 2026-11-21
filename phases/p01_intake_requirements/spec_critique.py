"""
AetherOS — Spec Critique module for P01 Intake Requirements.

Provides an LLM-powered pre-critique pass over the generated spec before it
is presented to the human reviewer.  Runs up to 2 passes; if no new issues
are found on the second pass the improved spec from the first pass is used.

Returns the improved spec text if issues were found, or the original if the
spec was already high quality.  Never blocks the pipeline — any exception is
caught, logged, and the original spec is returned unchanged.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from aether_os.core.llm.json_enforcer import extract_first_json

logger = logging.getLogger(__name__)

_CRITIQUE_SYSTEM = (
    "You are a senior software architect reviewing a project specification. "
    "Be concise, structured, and constructive."
)

_CRITIQUE_PROMPT_TMPL = """\
Review the following application specification and identify quality gaps.

SPEC:
{spec_text}

Evaluate and return ONLY valid JSON (no markdown, no fences):
{{
  "issues": [
    {{
      "category": "auth|entities|contradictions|error_cases|acceptance_criteria|other",
      "description": "specific issue found",
      "suggested_fix": "concrete fix for this issue"
    }}
  ],
  "improved_spec": "the full improved specification text with all issues addressed"
}}

Focus on:
1. Missing auth requirements (who can do what? login/logout/roles defined?)
2. Undefined entities (referenced but never described — name, fields, relationships)
3. Contradictory requirements (two statements that cannot both be true)
4. Missing error cases (what happens when payment fails? user not found? etc.)
5. Vague acceptance criteria (must be testable — avoid "fast", "user-friendly")

If the spec has no issues, return {{"issues": [], "improved_spec": "{spec_passthrough}"}}
"""

_PASSTHROUGH_SENTINEL = "__PASSTHROUGH__"


def _parse_critique_response(raw: str, original_spec: str) -> Dict[str, Any]:
    """Parse the LLM critique JSON response, falling back gracefully."""
    # The model often follows the JSON with an explanation or a second object; take the first
    # complete object rather than json.loads-ing the whole reply ("Extra data" in run 09297aa3).
    try:
        parsed = extract_first_json(raw, expect=dict)
    except ValueError as e:
        logger.warning("[spec_critique] Could not parse LLM response as JSON (%s): %s", e, (raw or "")[:200])
        return {"issues": [], "improved_spec": original_spec}

    # Normalise: ensure keys are present
    issues = parsed.get("issues") or []
    if not isinstance(issues, list):
        issues = [issues]
    improved = parsed.get("improved_spec") or original_spec
    if not isinstance(improved, str):
        logger.warning("[spec_critique] improved_spec is %s, not text — keeping the original", type(improved).__name__)
        improved = original_spec

    # If the LLM echoed the passthrough sentinel, keep original
    if _PASSTHROUGH_SENTINEL in improved or not improved.strip():
        improved = original_spec

    return {"issues": issues, "improved_spec": improved}


async def critique_spec(spec_text: str, llm_client: Any) -> str:
    """
    Run up to 2 LLM critique passes over spec_text.

    Returns the improved spec if issues were found in either pass,
    or the original spec if no issues were identified.

    Guard: if the LLM call errors on any pass, we log and return the
    best spec we have so far (never blocks the pipeline).

    Args:
        spec_text: The raw spec text produced by p01.
        llm_client: An initialised LLM client (from get_llm_client()).

    Returns:
        Improved spec string (or original if no improvement possible).
    """
    if not spec_text or not spec_text.strip():
        logger.debug("[spec_critique] Empty spec_text — skipping critique")
        return spec_text

    current_spec = spec_text
    MAX_PASSES = 2

    for pass_num in range(1, MAX_PASSES + 1):
        logger.info("[spec_critique] Starting critique pass %d/%d", pass_num, MAX_PASSES)
        try:
            prompt = _CRITIQUE_PROMPT_TMPL.format(
                spec_text=current_spec[:6000],
                spec_passthrough=_PASSTHROUGH_SENTINEL,
            )
            raw_response = await llm_client.call(
                prompt,
                task_type="analysis",
                system=_CRITIQUE_SYSTEM,
                max_tokens=2048,
            )
            result = _parse_critique_response(raw_response, current_spec)
            issues = result.get("issues") or []
            improved = result.get("improved_spec") or current_spec

            if not issues:
                logger.info(
                    "[spec_critique] Pass %d: no issues found — stopping early (spec is clean)",
                    pass_num,
                )
                # Return current_spec (which may already be improved from pass 1)
                return current_spec

            logger.info(
                "[spec_critique] Pass %d: %d issue(s) found — categories: %s",
                pass_num,
                len(issues),
                [i.get("category", "?") for i in issues],
            )
            for i, issue in enumerate(issues, 1):
                logger.debug(
                    "[spec_critique] Issue %d [%s]: %s → %s",
                    i,
                    issue.get("category", "?"),
                    issue.get("description", ""),
                    issue.get("suggested_fix", ""),
                )

            # Accept the improved spec for the next pass (or as final output)
            if improved and improved.strip() and improved != current_spec:
                logger.info("[spec_critique] Pass %d: spec improved (%d→%d chars)",
                            pass_num, len(current_spec), len(improved))
                current_spec = improved
            else:
                logger.debug("[spec_critique] Pass %d: LLM returned identical spec — keeping current", pass_num)

        except Exception as exc:
            logger.warning(
                "[spec_critique] Pass %d failed (non-fatal — using spec from previous pass): %s",
                pass_num, exc,
            )
            # Return whatever we have — never block the pipeline
            return current_spec

    logger.info("[spec_critique] Completed %d pass(es) — returning improved spec", MAX_PASSES)
    return current_spec
