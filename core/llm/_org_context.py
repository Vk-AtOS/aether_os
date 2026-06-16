"""
AetherOS — LLM org-context ContextVar

Kept in its own micro-module so that both client.py and providers.py can
import it without creating a circular dependency.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_current_org_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_current_org_id', default=None
)
