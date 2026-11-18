"""
Gap 1: Write compliance_manifest.json into the generated project root.

The drift_fingerprint is SHA-256 of all route-bearing .py source files.
It is stored at generation time and recomputed by the CI gate (Gap 3)
on every push to detect unauthorised code drift.

The manifest itself is built and written by core/compliance/manifest_writer.py (one implementation,
which never follows a link inside the run directory); this is p06's never-raising entry point.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from aether_os.core.compliance.manifest_writer import write_manifest_for_scan

logger = logging.getLogger(__name__)


def write_compliance_manifest(
    scan_result: Any,
    project_dir: Path,
    project_name: str,
    domain: str,
) -> Path | None:
    """
    Write compliance_manifest.json to the generated project root.

    Returns the Path to the written file, or None if writing failed.
    Never raises — logs all exceptions at WARNING level.
    """
    try:
        write_manifest_for_scan(scan_result, Path(project_dir), project_name, domain)
        return Path(project_dir) / "compliance_manifest.json"
    except Exception as exc:
        logger.warning("[p06] write_compliance_manifest failed: %s", exc)
        return None
