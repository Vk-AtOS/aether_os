"""Frontend pattern library — re-exports all four component strings.

Components are stored in two sub-modules to keep file sizes manageable:
  frontend_patterns_a.py — KANBAN_COMPONENT, COMMAND_PALETTE_COMPONENT
  frontend_patterns_b.py — NOTIFICATION_CENTER_COMPONENT, SETTINGS_PAGE_COMPONENT
"""
from __future__ import annotations

from aether_os.phases.patterns.frontend_patterns_a import (  # noqa: F401
    KANBAN_COMPONENT,
    COMMAND_PALETTE_COMPONENT,
)
from aether_os.phases.patterns.frontend_patterns_b import (  # noqa: F401
    NOTIFICATION_CENTER_COMPONENT,
    SETTINGS_PAGE_COMPONENT,
)

__all__ = [
    "KANBAN_COMPONENT",
    "COMMAND_PALETTE_COMPONENT",
    "NOTIFICATION_CENTER_COMPONENT",
    "SETTINGS_PAGE_COMPONENT",
]
