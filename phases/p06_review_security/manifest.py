"""
Gap 1: Write compliance_manifest.json into the generated project root.

The drift_fingerprint is SHA-256 of all route-bearing .py source files.
It is stored at generation time and recomputed by the CI gate (Gap 3)
on every push to detect unauthorised code drift.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
        # Collect source text from every .py file that contains route decorators.
        # Search project_dir/src first (canonical FastAPI layout), then project_dir.
        route_sources: list[str] = []
        for search_dir in (project_dir / "src", project_dir):
            if not search_dir.exists():
                continue
            for py_file in sorted(search_dir.rglob("*.py")):
                if "__pycache__" in str(py_file):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="replace")
                    if re.search(r'@(?:app|router)\.(get|post|put|delete|patch)', text):
                        route_sources.append(text)
                except Exception as read_err:
                    logger.warning(
                        "[p06] manifest: cannot read %s: %s", py_file, read_err
                    )
            if route_sources:
                break  # found route files at this level — stop descending

        drift_fingerprint = hashlib.sha256(
            "\n".join(route_sources).encode("utf-8")
        ).hexdigest() if route_sources else hashlib.sha256(b"").hexdigest()

        # Build per-component data from scan_result routes + findings
        components: list[dict] = []
        for route in getattr(scan_result, "routes", []):
            rules_satisfied: list[dict] = []
            rules_violated: list[dict] = []
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
                "file": Path(getattr(scan_result, "scanned_file", "")).name,
                "route": route_key,
                "has_auth": route.has_auth,
                "has_audit_log": route.has_audit_log,
                "has_input_validation": route.has_input_validation,
                "has_rate_limiting": route.has_rate_limit,
                "rules_satisfied": rules_satisfied,
                "rules_violated": rules_violated,
            })

        manifest: dict = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_name": project_name,
            "domain": domain,
            "overall_score": getattr(scan_result, "score", 0),
            "drift_fingerprint": drift_fingerprint,
            "framework_versions": {
                "HIPAA": "2024",
                "GDPR": "2018",
                "PCI-DSS": "4.0",
                "SOC2": "2017",
            },
            "components": components,
        }

        manifest_path = project_dir / "compliance_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info(
            "[p06] Gap 1: compliance_manifest.json written to %s (score=%d, routes=%d)",
            manifest_path, manifest["overall_score"], len(components),
        )
        return manifest_path

    except Exception as exc:
        logger.warning("[p06] write_compliance_manifest failed: %s", exc)
        return None
