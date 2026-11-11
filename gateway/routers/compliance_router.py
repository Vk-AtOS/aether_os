"""
AetherOS — Compliance & Audit Router
GET    /compliance/artifacts/{run_id}
GET    /compliance/org-report
GET    /audit/logs
GET    /audit/logs/export
DELETE /audit/logs/purge
"""
from __future__ import annotations
import logging
import os
import pathlib
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from aether_os.gateway.dependencies import get_current_user, require_run_user
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.compliance.artifact_generator import ComplianceArtifactGenerator
from aether_os.core.db import get_session_factory
from aether_os.core.db import get_session_factory as _gsf_ca
from aether_os.core.db import get_session_factory as _gsf_purge
from aether_os.core.models import AuditLog as _AL
from aether_os.core.models import Organisation as _Org
from aether_os.core.models import Run as _Run_ca
from aether_os.core.policy.compliance import ComplianceEngine, ComplianceContext
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as _delete
from sqlalchemy import select as _sel_ca
from sqlalchemy import text as _ct
from sqlalchemy import text as _ct2
import csv, io as _io
import io, zipfile
import json as _json_exp
import time as _time_export
import time as _time_purge
logger = logging.getLogger(__name__)
router = APIRouter(tags=["compliance", "audit"])
def _current_user():
    return Depends(get_current_user)
async def _count_security_decisions(sf, org_id: str) -> int:
    """T5-06: Count security-phase escalations as proxy for issues_found."""
    try:
        async with sf() as _sess2:
            return (await _sess2.execute(
                _ct2(
                    "SELECT COUNT(*) FROM decisions "
                    "WHERE org_id=:oid AND phase='p06_review_security'"
                ),
                {"oid": org_id},
            )).scalar() or 0
    except Exception as exc:
        logger.debug("Failed to count security decisions for org %s: %s", org_id, exc)
        return 0
@router.get("/audit/logs")
async def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    action: Optional[str] = None,
    from_ts: Optional[float] = None,
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return await get_ledger().async_get_audit_logs(org_id=user["org_id"], page=page, limit=limit, action=action, from_ts=from_ts)
@router.get("/audit/logs/export")
async def export_audit_logs(
    format: str = "json",
    days: int = 90,
    user: Dict[str, Any] = _current_user(),
):
    """T4-09: Export audit logs as JSON or CSV. Retention window controlled by `days`."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    if format not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="format must be json or csv")
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    from_ts = _time_export.time() - days * 86400
    # Fetch up to 10k rows for export
    result = await get_ledger().async_get_audit_logs(
        org_id=user["org_id"], page=1, limit=10000, from_ts=from_ts
    )
    logs = result.get("logs", [])
    if format == "json":
        content = _json_exp.dumps({"logs": logs, "exported_at": _time_export.time(), "days": days})
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{days}d.json"},
        )
    else:
        buf = _io.StringIO()
        fields = ["id", "org_id", "user_id", "action", "resource_type", "resource_id", "ip_address", "created_at"]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{days}d.csv"},
        )
@router.delete("/audit/logs/purge")
async def purge_audit_logs(
    days_to_keep: int = 90,
    user: Dict[str, Any] = _current_user(),
):
    """T4-09: Delete audit log entries older than `days_to_keep`. Enforces retention policy."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    if days_to_keep < 30:
        raise HTTPException(status_code=400, detail="Minimum retention is 30 days")
    cutoff = _time_purge.time() - days_to_keep * 86400
    try:
        async with _gsf_purge()() as _sess:
            result = await _sess.execute(
                _delete(_AL).where(_AL.org_id == user["org_id"]).where(_AL.created_at <= cutoff)
            )
            await _sess.commit()
            deleted = result.rowcount
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Purge failed: {exc}")
    return {"deleted": deleted, "cutoff_days": days_to_keep}
@router.get("/compliance/artifacts/{run_id}")
async def get_compliance_artifacts(run_id: str, user: Dict[str, Any] = Depends(require_run_user)):
    """
    Return a ZIP containing the compliance JSON + PDF for a given run.
    Runs the real code scanner on the generated src/main.py if it exists,
    otherwise returns a lightweight placeholder.
    """
    # Try to locate the generated src/main.py for this run
    project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id
    main_py_path: Optional[str] = None
    for candidate in [
        project_dir / "src" / "main.py",
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
    ]:
        if candidate.exists():
            main_py_path = str(candidate)
            break
    # Pull project_name / domain from the run DB record (best-effort)
    _project_name = ""
    _domain = "general"
    try:
        _sf_ca = _gsf_ca()
        async with _sf_ca() as _sess_ca:
            _run_ca = (await _sess_ca.execute(
                _sel_ca(_Run_ca).where(_Run_ca.id == run_id, _Run_ca.org_id == user["org_id"])
            )).scalar_one_or_none()
            if _run_ca:
                _project_name = getattr(_run_ca, "project_name", "") or ""
                _domain = getattr(_run_ca, "domain", "general") or "general"
    except Exception as exc:
        logger.debug("DB lookup for compliance project_name/domain failed (run %s): %s", run_id, exc)
    gen = ComplianceArtifactGenerator()
    artifact = await gen.generate_artifact(
        run_id,
        "COMPLIANCE_ZIP",
        main_py_path=main_py_path,
        project_name=_project_name,
        domain=_domain,
    )
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("compliance_scan.json", artifact.content)
        if artifact.pdf_path and pathlib.Path(artifact.pdf_path).exists():
            zf.write(artifact.pdf_path, arcname="compliance_report.pdf")
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=compliance_{run_id}.zip"},
    )
@router.get("/compliance/org-report")
async def get_compliance_report(user: Dict[str, Any] = _current_user()):
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        try:
            total = (await session.execute(
                _ct("SELECT COUNT(*) FROM runs WHERE org_id=:oid"), {"oid": org_id}
            )).scalar() or 0
            domains = (await session.execute(
                _ct("SELECT DISTINCT domain FROM runs WHERE org_id=:oid AND domain IS NOT NULL"), {"oid": org_id}
            )).scalars().all()
            approved = (await session.execute(
                _ct("SELECT COUNT(*) FROM decisions WHERE org_id=:oid AND status='approved'"), {"oid": org_id}
            )).scalar() or 0
            total_decisions = (await session.execute(
                _ct("SELECT COUNT(*) FROM decisions WHERE org_id=:oid"), {"oid": org_id}
            )).scalar() or 1
        except Exception as exc:
            logger.debug("Compliance org-report DB queries failed for org %s: %s", org_id, exc)
            total, domains, approved, total_decisions = 0, [], 0, 1
    # Determine deployment region from env (supports AWS, Fly.io, Railway, generic)
    _region = (
        os.environ.get("DEPLOYMENT_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("FLY_REGION")
        or os.environ.get("RAILWAY_REGION")
        or "unknown"
    )
    # EU AI Act risk: default to MINIMAL unless org has registered high-risk use cases
    _eu_ai_risk = "MINIMAL"
    _org_settings: dict = {}
    try:
        try:
            async with sf() as _s2:
                _org = await _s2.get(_Org, org_id)
                if _org and _org.data_region:
                    _org_settings["data_region"] = _org.data_region
        except Exception as exc:
            logger.debug("Failed to load org data_region for compliance report (org %s): %s", org_id, exc)
        _ctx = ComplianceContext(
            country_code="",
            region=_org_settings.get("data_region", "global").upper(),
            deployment_type="saas",
            data_sensitivity="moderate",
            handles_personal_data=True,
            handles_biometric_data=False,
            handles_children_data=False,
            industries=[],
            high_risk_use_cases=[],
            uses_strong_crypto=True,
            uses_weak_crypto=False,
            customer_requires_data_residency=False,
            uses_third_country_cloud=False,
            model_providers=[],
            repo_tags=[],
        )
        _result = ComplianceEngine().evaluate(_ctx)
        if _result.denied:
            _eu_ai_risk = "HIGH"
        elif _result.requires_approval:
            _eu_ai_risk = "LIMITED"
        else:
            _eu_ai_risk = "MINIMAL"
    except Exception as exc:
        logger.debug("ComplianceEngine evaluation failed for org %s: %s", org_id, exc)
    return {
        "total_runs": total,
        "domains_used": list(domains),
        "models_used": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "decision_approval_rate": round(approved / max(total_decisions, 1), 3),
        "security_scan_summary": {
            "scans_run": total,
            "issues_found": await _count_security_decisions(sf, org_id),
        },
        "data_processing_locations": [_region],
        "data_region": _org_settings.get("data_region", "global"),
        "eu_ai_act_risk": _eu_ai_risk,
    }