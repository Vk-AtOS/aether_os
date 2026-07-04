"""Domain-specific page injector for p05_frontend.

Writes social/IoT/ERP/feature-flag pages into src/pages/ and patches
App.tsx routing + Layout.tsx sidebar nav to include them. Called from
task_agent.py after entity CRUD pages are generated.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _guard_write(path: Path, content: str) -> None:
    """Write only when content differs to avoid unnecessary disk I/O."""
    if path.exists() and path.read_text() == content:
        return
    path.write_text(content)


def _patch_app_tsx(app_tsx: Path, routes: list[tuple[str, str, str]]) -> None:
    """Idempotently add page imports, route definitions, and children to App.tsx."""
    if not app_tsx.exists() or not routes:
        return
    try:
        text = app_tsx.read_text()

        new_imports = "\n".join(
            f"import {page} from './pages/{page}'"
            for _, _, page in routes
            if f"import {page} " not in text
        )
        if new_imports and "import NotFoundPage" in text:
            text = text.replace(
                "import NotFoundPage from './pages/NotFoundPage'",
                f"{new_imports}\nimport NotFoundPage from './pages/NotFoundPage'",
                1,
            )

        new_defs = "\n\n".join(
            f"const {var} = createRoute({{ getParentRoute: () => layoutRoute, "
            f"path: '{path}', component: {page} }})"
            for var, path, page in routes
            if f"const {var} " not in text
        )
        if new_defs and "const routeTree = " in text:
            text = text.replace("const routeTree = ", f"{new_defs}\n\nconst routeTree = ", 1)

        for var, _, _ in routes:
            child = f"    {var},"
            if child not in text and "  ]),\n])" in text:
                text = text.replace("  ]),\n])", f"  {child}\n  ]),\n])", 1)

        app_tsx.write_text(text)
        logger.info("domain_pages: patched App.tsx with %d domain routes", len(routes))
    except Exception as e:
        logger.warning("domain_pages: App.tsx patch failed: %s", e)


def _patch_layout_tsx(
    layout_tsx: Path,
    nav_entries: list[tuple[str, str, str]],  # (path, label, icon)
) -> None:
    """Idempotently add domain nav items to the SIDEBAR_NAV / BOTTOM_NAV in Layout.tsx."""
    if not layout_tsx.exists() or not nav_entries:
        return
    try:
        text = layout_tsx.read_text()

        # Collect icons not yet imported and add them to the lucide-react import line
        icons_to_add = [
            icon for _, _, icon in nav_entries
            if f" {icon}," not in text and f" {icon} " not in text and f"{{{icon}}}" not in text
        ]
        if icons_to_add and "} from 'lucide-react'" in text:
            text = text.replace(
                "} from 'lucide-react'",
                f", {', '.join(icons_to_add)} }} from 'lucide-react'",
                1,
            )

        # Add entries to SIDEBAR_NAV and BOTTOM_NAV before the closing ]
        for path, label, icon in nav_entries:
            entry = f"  {{ to: '{path}' as const, label: '{label}', icon: '{icon}' }},"
            if entry not in text:
                # Insert into SIDEBAR_NAV
                if "const SIDEBAR_NAV = [" in text:
                    text = text.replace(
                        "\n]\n\nexport function Layout",
                        f"\n{entry}\n]\n\nexport function Layout",
                        1,
                    )
                # Insert into BOTTOM_NAV as well (first 4 items cap is fine — layout clips extras)
                if "const BOTTOM_NAV = [" in text:
                    text = text.replace(
                        "\n]\n\n// Sidebar",
                        f"\n{entry}\n]\n\n// Sidebar",
                        1,
                    )

        layout_tsx.write_text(text)
        logger.info("domain_pages: patched Layout.tsx with %d nav entries", len(nav_entries))
    except Exception as e:
        logger.warning("domain_pages: Layout.tsx patch failed: %s", e)


def write_domain_pages(src_dir: Path, domain: str, build_types: List[str]) -> None:
    """Write domain-specific pages and patch App.tsx routing + Layout.tsx nav.

    Activated by domain keyword or build_types list populated by pattern_injector.
    All operations are idempotent — safe to call on repeated pipeline runs.
    """
    pages_dir = src_dir / "pages"
    app_tsx = src_dir / "App.tsx"
    layout_tsx = src_dir / "components" / "Layout.tsx"
    extra_routes: list[tuple[str, str, str]] = []   # (route_var, path, PageName)
    extra_nav:    list[tuple[str, str, str]] = []   # (path, label, icon)

    _has_social = domain in ("social", "social_platform") or "social_graph" in build_types
    _has_iot    = domain == "iot" or "iot_timeseries" in build_types
    _has_erp    = "erp" in build_types or "approval" in build_types
    _has_flags  = "feature_flags" in build_types

    try:
        if _has_social:
            from aether_os.phases.patterns.frontend_patterns_c import (  # noqa: PLC0415
                FEED_PAGE_TSX,
                FOLLOWERS_PAGE_TSX,
            )
            _guard_write(pages_dir / "FeedPage.tsx", FEED_PAGE_TSX)
            _guard_write(pages_dir / "FollowersPage.tsx", FOLLOWERS_PAGE_TSX)
            extra_routes += [
                ("feedRoute",      "/feed",      "FeedPage"),
                ("followersRoute", "/followers", "FollowersPage"),
            ]
            extra_nav += [
                ("/feed",      "Feed",        "Rss"),
                ("/followers", "Connections", "Users"),
            ]
            logger.info("domain_pages: wrote social pages (FeedPage, FollowersPage)")

        if _has_iot:
            from aether_os.phases.patterns.frontend_patterns_d import (  # noqa: PLC0415
                DEVICE_FLEET_PAGE_TSX,
                SENSOR_CHART_PAGE_TSX,
            )
            _guard_write(pages_dir / "DeviceFleetPage.tsx", DEVICE_FLEET_PAGE_TSX)
            _guard_write(pages_dir / "SensorChartPage.tsx", SENSOR_CHART_PAGE_TSX)
            extra_routes += [
                ("deviceFleetRoute", "/devices",                    "DeviceFleetPage"),
                ("sensorChartRoute", "/devices/$deviceId/readings", "SensorChartPage"),
            ]
            extra_nav += [
                ("/devices", "Device Fleet", "Server"),
            ]
            logger.info("domain_pages: wrote iot pages (DeviceFleetPage, SensorChartPage)")

        if _has_erp:
            from aether_os.phases.patterns.frontend_patterns_e import (  # noqa: PLC0415
                APPROVAL_QUEUE_PAGE_TSX,
            )
            _guard_write(pages_dir / "ApprovalQueuePage.tsx", APPROVAL_QUEUE_PAGE_TSX)
            extra_routes += [("approvalRoute", "/approvals", "ApprovalQueuePage")]
            extra_nav    += [("/approvals", "Approvals", "CheckSquare")]
            logger.info("domain_pages: wrote erp page (ApprovalQueuePage)")

        if _has_flags:
            from aether_os.phases.patterns.frontend_patterns_e import (  # noqa: PLC0415
                FLAG_ADMIN_PAGE_TSX,
            )
            _guard_write(pages_dir / "FlagAdminPage.tsx", FLAG_ADMIN_PAGE_TSX)
            extra_routes += [("flagsRoute", "/flags", "FlagAdminPage")]
            extra_nav    += [("/flags", "Feature Flags", "Flag")]
            logger.info("domain_pages: wrote flags page (FlagAdminPage)")

    except Exception as e:
        logger.warning("domain_pages: write failed: %s", e)
        return

    _patch_app_tsx(app_tsx, extra_routes)
    _patch_layout_tsx(layout_tsx, extra_nav)
