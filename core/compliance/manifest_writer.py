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
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
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


def write_compliance_manifest(
    project_path: str,
    domain: str,
    project_name: str,
) -> dict:
    """
    Scan all .py files under project_path and write compliance_manifest.json.

    Steps:
    1. Find all .py files under project_path
    2. Run code_scanner.scan_file on the main entry point (src/main.py preferred)
    3. Build manifest dict from scan results
    4. Compute drift fingerprint from route-bearing files
    5. Write compliance_manifest.json to project_path root
    6. Return the manifest dict

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
            if candidate.exists():
                main_py = candidate
                break

        if not main_py:
            logger.warning(
                "[manifest_writer] no main.py found under %s — writing empty manifest",
                project_path,
            )
            manifest = {**empty_manifest}
        else:
            scan_result = scan_file(main_py, project_name=project_name, domain=domain)
            scanned_file = getattr(scan_result, "scanned_file", str(main_py))
            components = _build_components_from_scan(scan_result, scanned_file)
            drift_fingerprint = _compute_drift_fingerprint(_path)

            manifest = {
                "schema_version": "1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_name": project_name,
                "domain": domain,
                "overall_score": getattr(scan_result, "score", 0),
                "drift_fingerprint": drift_fingerprint,
                "framework_versions": _FRAMEWORK_VERSIONS,
                "components": components,
            }

        manifest_path = _path / "compliance_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info(
            "[manifest_writer] wrote compliance_manifest.json to %s (score=%d, routes=%d)",
            manifest_path,
            manifest.get("overall_score", 0),
            len(manifest.get("components", [])),
        )
        return manifest

    except Exception as exc:
        logger.warning("[manifest_writer] write_compliance_manifest failed: %s", exc)
        return empty_manifest
