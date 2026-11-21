"""
G1: Compliance Manifest Writer — standalone module under core/compliance.

Runs the code scanner against all .py files in a generated project and writes
compliance_manifest.json to the project root.

Public API:
    write_compliance_manifest(project_path, domain, project_name) -> dict
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)

_FRAMEWORK_VERSIONS: Dict[str, str] = {
    "HIPAA": "2024",
    "GDPR": "2018",
    "PCI-DSS": "4.0",
    "SOC2": "2017",
}


def _compute_drift_fingerprint(project_path: Path) -> str:
    """SHA-256 of all route-bearing .py files concatenated in sorted order."""
    route_sources: List[str] = []
    for search_dir in (project_path / "src", project_path):
        # project_path is the run dir: no link below it is followed (KAN-63)
        if not safe_fs.is_real_dir(project_path, search_dir.relative_to(project_path)):
            continue
        for rel in safe_fs.walk_files(project_path, search_dir.relative_to(project_path),
                                      skip_dirs=("__pycache__",)):
            py_file = project_path / rel
            if py_file.suffix != ".py":
                continue
            try:
                text = safe_fs.read_text_or_none(project_path, py_file) or ""
                if re.search(r"@(?:app|router)\.(get|post|put|delete|patch)", text):
                    route_sources.append(text)
            except Exception as exc:
                logger.warning("[manifest_writer] cannot read %s: %s", py_file, exc)
        if route_sources:
            break
    combined = "\n".join(route_sources).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _build_components_from_scan(scan_result: Any, scanned_file_path: str) -> List[dict]:
    """Convert code_scanner.ComplianceScanResult into manifest component list."""
    components: List[dict] = []
    for route in getattr(scan_result, "routes", []):
        rules_satisfied: List[dict] = []
        rules_violated: List[dict] = []
        route_key = f"{route.method} {route.path}"
        for finding in getattr(scan_result, "findings", []):
            if route_key not in (finding.routes_affected or []):
                continue
            entry = {"id": finding.rule_id, "name": finding.rule_name}
            if finding.severity == "pass":
                rules_satisfied.append(entry)
            else:
                rules_violated.append({
                    **entry,
                    "severity": finding.severity,
                    "remediation": finding.remediation,
                })
        components.append({
            "file": Path(scanned_file_path).name if scanned_file_path else "main.py",
            "route": route_key,
            "has_auth": route.has_auth,
            "has_audit_log": route.has_audit_log,
            "has_input_validation": route.has_input_validation,
            "has_rate_limiting": route.has_rate_limit,
            "rules_satisfied": rules_satisfied,
            "rules_violated": rules_violated,
        })
    return components


def write_manifest_for_scan(scan_result: Any, project_path: Path, project_name: str, domain: str) -> dict:
    """Build the manifest from an existing scan result and write compliance_manifest.json into the run
    directory. The one writer (p06 calls it): nothing under project_path is read or written through a link.
    Raises on failure (SandboxViolation if the manifest path is a planted link)."""
    _path = Path(project_path)
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
        "domain": domain,
        "overall_score": getattr(scan_result, "score", 0),
        "drift_fingerprint": _compute_drift_fingerprint(_path),
        "framework_versions": _FRAMEWORK_VERSIONS,
        "components": _build_components_from_scan(scan_result, getattr(scan_result, "scanned_file", "")),
    }
    safe_fs.safe_write_text(_path, _path / "compliance_manifest.json", json.dumps(manifest, indent=2))
    logger.info("[manifest_writer] wrote compliance_manifest.json to %s (score=%d, routes=%d)",
                _path, manifest["overall_score"], len(manifest["components"]))
    return manifest


def write_compliance_manifest(
    project_path: str,
    domain: str,
    project_name: str,
) -> dict:
    """
    Scan the project's main.py and write compliance_manifest.json (for callers with no scan result yet).

    Never raises — logs all failures at WARNING. Returns empty manifest on failure.
    """
    _path = Path(project_path)
    empty_manifest: dict = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
        "domain": domain,
        "overall_score": 0,
        "drift_fingerprint": hashlib.sha256(b"").hexdigest(),
        "framework_versions": _FRAMEWORK_VERSIONS,
        "components": [],
    }

    try:
        from aether_os.core.compliance.code_scanner import scan_file

        # Resolve main entry point for scanning
        main_py: Optional[Path] = None
        for candidate in (
            _path / "src" / "main.py",
            _path / "main.py",
            _path / "app" / "main.py",
        ):
            if safe_fs.stat_or_none(_path, candidate) is not None:
                main_py = candidate
                break

        if not main_py:
            logger.warning(
                "[manifest_writer] no main.py found under %s — writing empty manifest",
                project_path,
            )
            safe_fs.safe_write_text(_path, _path / "compliance_manifest.json", json.dumps(empty_manifest, indent=2))
            return empty_manifest
        scan_result = scan_file(main_py, project_name=project_name, domain=domain, root=_path)
        return write_manifest_for_scan(scan_result, _path, project_name, domain)

    except Exception as exc:
        logger.warning("[manifest_writer] write_compliance_manifest failed: %s", exc)
        return empty_manifest
