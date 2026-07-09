"""
AetherOS — LLM org-context and provider-override ContextVars

Kept in its own micro-module so that both client.py and providers.py can
import it without creating a circular dependency.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_current_org_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_current_org_id', default=None
)

# Per-async-task provider override — replaces the os.environ["PRIMARY_LLM"] global
# mutation which caused race conditions under concurrent pipeline runs.
# Use _active_provider.set(provider) with the returned token and reset in finally.
_active_provider: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_active_provider', default=None
)
