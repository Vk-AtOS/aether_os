"""Per-run context variables shared by the orchestrator and the LLM layer.

Kept in core so core/model_router and core/llm never import the orchestrator (KAN-183):
the orchestrator sets them, the LLM layer reads them. orchestrator.events re-exports the
same objects for existing callers.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

# Set by factory_pipeline before each phase so LLM calls can emit to the right queue.
ACTIVE_RUN_ID: ContextVar[Optional[str]] = ContextVar("active_run_id", default=None)
# Phase name currently executing (for tagging llm_chunk events)
ACTIVE_PHASE: ContextVar[Optional[str]] = ContextVar("active_phase", default=None)
# Org ID for the active run (for cost tracking)
ACTIVE_ORG_ID: ContextVar[Optional[str]] = ContextVar("active_org_id", default=None)
