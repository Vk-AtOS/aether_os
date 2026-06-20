"""
Cloud Console Generator — AetherOS P05 Layer 7.

Triggered when build_profile.build_type == "cloud_platform".
Orchestrates all generators from cloud_console_app.py and cloud_console_pages.py
to produce a React + Vite cloud management console at output_dir/frontend/.

File split rationale (600-line rule):
  cloud_console_app.py  — app-shell: package.json, index.html, main.jsx, App.jsx, vite.config
  cloud_console_pages.py — route pages: Dashboard, ServiceCatalog, ResourceExplorer, CostDashboard, Settings
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from aether_os.phases.p05_frontend.cloud_console_app import (
    generate_console_package_json,
    generate_console_index_html,
    generate_console_main_jsx,
    generate_console_app_jsx,
    generate_console_vite_config,
)
from aether_os.phases.p05_frontend.cloud_console_pages import (
    generate_dashboard_jsx,
    generate_service_catalog_jsx,
    generate_resource_explorer_jsx,
    generate_cost_dashboard_jsx,
    generate_settings_jsx,
)

logger = logging.getLogger(__name__)


def _label(name: str) -> str:
    return name.replace("_", " ").title()


async def generate_cloud_console(
    entities: List[Dict],
    services: List[Dict],
    project_name: str,
    output_dir: Path,
) -> Path:
    """Write all console files to output_dir/frontend/ and return that path.

    If services is empty, each entity is promoted to a service with a default
    description and icon so the catalog always has something to show.
    """
    if not services:
        services = [
            {
                "name": e.get("table", e.get("name", "resource")),
                "description": f"Manage {_label(e.get('table', e.get('name', 'resource')))} resources",
                "icon": "📦",
            }
            for e in entities
        ]

    frontend_dir = output_dir / "frontend"
    src_dir = frontend_dir / "src"
    pages_dir = src_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    (frontend_dir / "package.json").write_text(generate_console_package_json(project_name))
    (frontend_dir / "vite.config.js").write_text(generate_console_vite_config())
    (frontend_dir / "index.html").write_text(generate_console_index_html(project_name))
    (src_dir / "main.jsx").write_text(generate_console_main_jsx())
    (src_dir / "App.jsx").write_text(generate_console_app_jsx(services))
    (pages_dir / "Dashboard.jsx").write_text(generate_dashboard_jsx(services))
    (pages_dir / "ServiceCatalog.jsx").write_text(generate_service_catalog_jsx(services))
    (pages_dir / "ResourceExplorer.jsx").write_text(generate_resource_explorer_jsx(entities))
    (pages_dir / "CostDashboard.jsx").write_text(generate_cost_dashboard_jsx())
    (pages_dir / "Settings.jsx").write_text(generate_settings_jsx())

    logger.info(
        "cloud_console_generator: wrote console to %s (%d services, %d entity types)",
        frontend_dir, len(services), len(entities),
    )
    return frontend_dir
