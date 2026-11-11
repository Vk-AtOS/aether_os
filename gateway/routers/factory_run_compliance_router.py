"""
AetherOS — Factory Run Compliance Router

Routes (compliance, decisions, portal):
  GET /factory/runs/{run_id}/compliance
  GET /factory/runs/{run_id}/decisions
  GET /factory/runs/{run_id}/portal
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user, require_run_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run-compliance"])


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/compliance")
async def get_run_compliance(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """
    Return the compliance scan result for a pipeline run.

    1. If a pre-generated compliance_scan.json exists (written by p06), return it.
    2. Otherwise run the real scanner on-demand against src/main.py.
    3. If neither is available, return a graceful 404-style response rather
       than raising so the UI can show a clear "not yet scanned" state.
    """
    from aether_os.core.compliance.code_scanner import scan_file
    from aether_os.core.compliance.pdf_report import generate_pdf
    from dataclasses import asdict

    project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id

    # Fast path: p06 already wrote the JSON
    pre_built = project_dir / "p06_review_security" / "compliance" / "compliance_scan.json"
    if pre_built.exists():
        try:
            data = json.loads(pre_built.read_text(encoding="utf-8"))
            pdf_sibling = pre_built.with_name("compliance_report.pdf")
            data["pdf_path"] = str(pdf_sibling) if pdf_sibling.exists() else None
            return data
        except Exception as exc:
            logger.debug(
                "Failed to read pre-built compliance_scan.json for run %s, "
                "falling through to on-demand scan: %s",
                run_id, exc,
            )

    # On-demand scan: find src/main.py
    main_py: Optional[pathlib.Path] = None
    for candidate in [
        project_dir / "src" / "main.py",
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
    ]:
        if candidate.exists():
            main_py = candidate
            break

    if not main_py:
        return {
            "run_id": run_id,
            "status": "not_available",
            "message": "Code generation has not completed yet or src/main.py was not found.",
            "score": None,
            "findings": [],
        }

    # Pull project_name / domain from DB (best-effort)
    _project_name = ""
    _domain = "general"
    try:
        from aether_os.core.db import get_session_factory as _gsf_rc
        from aether_os.core.models import Run as _Run_rc
        from sqlalchemy import select as _sel_rc

        _sf_rc = _gsf_rc()
        async with _sf_rc() as _sess_rc:
            _run_rc = (
                await _sess_rc.execute(
                    _sel_rc(_Run_rc).where(
                        _Run_rc.id == run_id, _Run_rc.org_id == user["org_id"]
                    )
                )
            ).scalar_one_or_none()
            if _run_rc:
                _project_name = getattr(_run_rc, "project_name", "") or ""
                _domain = getattr(_run_rc, "domain", "general") or "general"
    except Exception as exc:
        logger.debug(
            "DB lookup for compliance project_name/domain failed (run %s): %s", run_id, exc
        )

    scan_result = scan_file(main_py, project_name=_project_name, domain=_domain)

    # Persist the result so subsequent calls are fast
    pdf_path = None
    try:
        scan_dir = project_dir / "p06_review_security" / "compliance"
        scan_dir.mkdir(parents=True, exist_ok=True)
        json_path = scan_dir / "compliance_scan.json"
        json_path.write_text(
            json.dumps(asdict(scan_result), indent=2, default=str),
            encoding="utf-8",
        )
        pdf_path = scan_dir / "compliance_report.pdf"
        generate_pdf(scan_result, pdf_path)
    except Exception as exc:
        logger.debug(
            "Failed to persist compliance scan result to disk for run %s: %s", run_id, exc
        )
        pdf_path = None

    result_dict = asdict(scan_result)
    result_dict["pdf_path"] = str(pdf_path) if pdf_path and pdf_path.exists() else None
    return result_dict


@router.get("/factory/runs/{run_id}/decisions")
async def get_run_decisions(
    run_id: str,
    status: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """List decisions (spec approvals, phase gates) for a run."""
    from aether_os.core.decisions.decision_engine import get_decision_engine

    engine = get_decision_engine()
    decisions = await engine.list_for_run(run_id, status=status)
    return [d.to_dict() for d in decisions]


@router.get("/factory/runs/{run_id}/portal")
async def get_run_portal(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return portal HTML content path and run summary.

    Returns 404 with detail portal_not_generated if no portal data exists.
    """
    from aether_os.core.db import get_session_factory as _gsf_portal
    from aether_os.core.models import Run as _Run_portal
    from sqlalchemy import select as _sel_portal

    async with _gsf_portal()() as _sess_portal:
        _run_p = (
            await _sess_portal.execute(
                _sel_portal(_Run_portal).where(
                    _Run_portal.id == run_id,
                    _Run_portal.org_id == user["org_id"],
                )
            )
        ).scalar_one_or_none()
    if not _run_p:
        raise HTTPException(status_code=404, detail="Run not found")

    _project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id

    # Look for portal output from p14 or p10
    _portal_html: Optional[str] = None
    _portal_candidates = [
        _project_dir / "p14_client_portal" / "portal" / "index.html",
        _project_dir / "p14_client_portal" / "index.html",
        _project_dir / "p10_docs_delivery" / "portal" / "index.html",
        _project_dir / "p10_docs_delivery" / "index.html",
    ]
    for _cand in _portal_candidates:
        if _cand.exists():
            _portal_html = str(_cand.relative_to(_project_dir))
            break

    if not _portal_html:
        raise HTTPException(status_code=404, detail="portal_not_generated")

    # Gather deliverables list
    _deliverables = []
    for _phase in ("p10_docs_delivery", "p14_client_portal"):
        _phase_dir = _project_dir / _phase
        if _phase_dir.exists():
            for _f in sorted(_phase_dir.rglob("*")):
                if _f.is_file() and _f.suffix in (".html", ".pdf", ".zip", ".md", ".json"):
                    _deliverables.append({
                        "filename": _f.name,
                        "path": str(_f.relative_to(_project_dir)),
                        "size_bytes": _f.stat().st_size,
                    })

    _council = _run_p.council_delivery or {}
    return {
        "run_id": run_id,
        "portal_html_path": _portal_html,
        "summary": {
            "project_name": _run_p.project_name or f"project-{run_id[:8]}",
            "status": _run_p.status,
            "quality_score": _run_p.quality_score,
            "council_verdict": (
                "passed" if _council.get("passed")
                else ("failed" if _council else "pending")
            ),
        },
        "deliverables": _deliverables,
    }
