"""
AetherOS — Pipeline run-state helpers.

Extracted from factory_pipeline.py. Contains:
  - _extract_project_name(): derive a Python-safe project name from raw input
  - Pipeline concurrency semaphore management
  - update_phase_state(): persist phase status via ORM
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_project_name(raw_input: str, run_id: str) -> str:
    """Extract a Python-safe project name from raw_input, fallback to RunId{run_id[:8]}.

    Tries: "Build X" / "Build the X" pattern first, then first capitalised word
    that looks like a product name. Returns a PascalCase identifier — no hyphens.
    """
    import re as _re
    if raw_input:
        m = _re.search(r'\bBuild(?:\s+the\s+|\s+)([A-Z][A-Za-z0-9]+)', raw_input)
        if m:
            return _re.sub(r'[^A-Za-z0-9]', '', m.group(1)) or f"Run{run_id[:8]}"
        m = _re.search(r'([A-Z][A-Za-z0-9]+(?:[A-Z][A-Za-z0-9]+)+)', raw_input)
        if m:
            return _re.sub(r'[^A-Za-z0-9]', '', m.group(1)) or f"Run{run_id[:8]}"
    return f"Run{run_id[:8]}"


# ── Pipeline concurrency limiter ──────────────────────────────────────────────
# Prevents CPU saturation when multiple users trigger simultaneous builds.
# Default: 2 concurrent full pipeline runs. Override with PIPELINE_MAX_CONCURRENT env var.
_PIPELINE_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_pipeline_semaphore() -> asyncio.Semaphore:
    global _PIPELINE_SEMAPHORE
    if _PIPELINE_SEMAPHORE is None:
        limit = int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2"))
        _PIPELINE_SEMAPHORE = asyncio.Semaphore(limit)
    return _PIPELINE_SEMAPHORE


def _serialisable(v: object) -> object:
    """Recursively convert arbitrary values to JSON-safe primitives."""
    if isinstance(v, dict):
        return {k2: _serialisable(v2) for k2, v2 in v.items()}
    if isinstance(v, list):
        return [_serialisable(i) for i in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


async def save_checkpoint(run_id: str, phase_name: str, accumulated_context: dict) -> None:
    """Persist a checkpoint to the Run record so a crashed run can resume."""
    try:
        from aether_os.core.db import get_session_factory as _gsf_ckpt_w
        from aether_os.core.models import Run as _Run_ckpt_w
        from sqlalchemy import update as _sa_upd_ckpt_w

        _ckpt_ctx = {
            k: _serialisable(v)
            for k, v in accumulated_context.items()
            if k not in ("phase_summaries",)
        }
        _ckpt_payload = {
            "last_completed_phase": phase_name,
            "accumulated_context": _ckpt_ctx,
        }
        async with _gsf_ckpt_w()() as _sess_ckpt_w:
            await _sess_ckpt_w.execute(
                _sa_upd_ckpt_w(_Run_ckpt_w)
                .where(_Run_ckpt_w.id == run_id)
                .values(checkpoint_data=_ckpt_payload)
            )
            await _sess_ckpt_w.commit()
    except Exception as _ckpt_w_exc:
        logger.debug("[pipeline] checkpoint save failed (non-fatal): %s", _ckpt_w_exc)


async def update_phase_state(run_id: str, phase: str, status: str) -> None:
    """Persist phase status via ORM (FIX-017)."""
    try:
        from aether_os.core.db import get_session_factory as _gsf_us
        from aether_os.core.models import PhaseCompletion as _PC_us
        async with _gsf_us()() as _sess_us:
            existing_pc = (await _sess_us.get(_PC_us, (run_id, phase)))
            if existing_pc:
                now = time.time()
                # The row's updated_at is when it went "running": the time to the next status is the phase's duration.
                # Nothing ever set duration_s, so it was NULL on every row (KAN-274 G10).
                if existing_pc.status == "running" and status != "running" and existing_pc.updated_at:
                    existing_pc.duration_s = max(0.0, now - existing_pc.updated_at)
                existing_pc.status = status
                existing_pc.updated_at = now
            else:
                _sess_us.add(_PC_us(
                    run_id=run_id,
                    phase_name=phase,
                    status=status,
                    updated_at=time.time(),
                ))
            await _sess_us.commit()
    except Exception as e:
        logger.warning("State update failed: %s", e)
