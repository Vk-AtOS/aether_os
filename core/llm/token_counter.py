"""
AetherOS — Token Counter & Cost Registry

Tracks prompt/completion token counts across all LLM calls and provides the
LLM trace persistence helper (_write_llm_trace).  Kept separate so that
cost-tracking state can be imported without pulling in provider SDKs.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── In-process cost accumulator ───────────────────────────────────────────────
_cost_registry: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


def safe_parse_json(text: str) -> dict:
    """Parse a JSON string that may be wrapped in markdown fences or have other noise."""
    # Try direct parse
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        logger.warning("token_counter: direct JSON parse failed: %s", e)
    # Find JSON block anywhere in response
    for pattern in [r'\{[^{}]*\}', r'\{.*?\}']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("token_counter: failed to parse JSON block from pattern %r: %s", pattern, e)
    # Last resort — return structured default
    return {"content": text.strip(), "parse_error": True, "raw": text[:1000]}


async def _write_llm_trace(
    run_id: Optional[str],
    phase: str,
    task_type: str,
    model: str,
    prompt: str,
    raw_response: str,
    parsed_ok: bool,
    error: Optional[str],
    attempt: int,
    duration_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Write one row to llm_traces. Non-blocking — failures are swallowed (FIX 22)."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import LLMTrace
        async with get_session_factory()() as db:
            trace = LLMTrace(
                id=str(uuid.uuid4()),
                run_id=run_id,
                phase=phase,
                task_type=task_type,
                model=model,
                prompt=prompt[:50000],       # cap at 50K chars
                raw_response=raw_response[:50000],
                parsed_ok=parsed_ok,
                error=error,
                attempt=attempt,
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            db.add(trace)
            await db.commit()
    except Exception as _trace_exc:
        logging.getLogger(__name__).debug("LLM trace write failed (non-blocking): %s", _trace_exc)
