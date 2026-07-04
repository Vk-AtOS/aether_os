"""Frontend pattern library — re-exports all component strings.

Components are stored in sub-modules to keep file sizes manageable:
  frontend_patterns_a.py  — KANBAN_COMPONENT, COMMAND_PALETTE_COMPONENT
  frontend_patterns_b.py  — NOTIFICATION_CENTER_COMPONENT
  frontend_patterns_b2.py — SETTINGS_PAGE_COMPONENT
  frontend_patterns_c.py  — FEED_PAGE_TSX, FOLLOWERS_PAGE_TSX (social)
  frontend_patterns_d.py  — DEVICE_FLEET_PAGE_TSX, SENSOR_CHART_PAGE_TSX (iot)
  frontend_patterns_e.py  — APPROVAL_QUEUE_PAGE_TSX, FLAG_ADMIN_PAGE_TSX (erp/flags)
"""
from __future__ import annotations

from aether_os.phases.patterns.frontend_patterns_a import (  # noqa: F401
    KANBAN_COMPONENT,
    COMMAND_PALETTE_COMPONENT,
)
from aether_os.phases.patterns.frontend_patterns_b import (  # noqa: F401
    NOTIFICATION_CENTER_COMPONENT,
)
from aether_os.phases.patterns.frontend_patterns_b2 import (  # noqa: F401
    SETTINGS_PAGE_COMPONENT,
)
from aether_os.phases.patterns.frontend_patterns_c import (  # noqa: F401
    FEED_PAGE_TSX,
    FOLLOWERS_PAGE_TSX,
)
from aether_os.phases.patterns.frontend_patterns_d import (  # noqa: F401
    DEVICE_FLEET_PAGE_TSX,
    SENSOR_CHART_PAGE_TSX,
)
from aether_os.phases.patterns.frontend_patterns_e import (  # noqa: F401
    APPROVAL_QUEUE_PAGE_TSX,
    FLAG_ADMIN_PAGE_TSX,
)

__all__ = [
    "KANBAN_COMPONENT",
    "COMMAND_PALETTE_COMPONENT",
    "NOTIFICATION_CENTER_COMPONENT",
    "SETTINGS_PAGE_COMPONENT",
    "FEED_PAGE_TSX",
    "FOLLOWERS_PAGE_TSX",
    "DEVICE_FLEET_PAGE_TSX",
    "SENSOR_CHART_PAGE_TSX",
    "APPROVAL_QUEUE_PAGE_TSX",
    "FLAG_ADMIN_PAGE_TSX",
]
