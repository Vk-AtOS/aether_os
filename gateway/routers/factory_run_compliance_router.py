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
import tempfile
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from aether_os.core.run_app import safe_fs
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
    # (safe_fs: the sandboxed app writes in project_dir; a planted link reads as absent)
    pre_rel = "p06_review_security/compliance/compliance_scan.json"
    pre_text = safe_fs.read_text_or_none(project_dir, pre_rel)
    if pre_text is not None:
        try:
            data = json.loads(pre_text)
            has_pdf = safe_fs.file_size_or_none(project_dir, "p06_review_security/compliance/compliance_report.pdf") is not None
            data["pdf_path"] = str(project_dir / "p06_review_security/compliance/compliance_report.pdf") if has_pdf else None
            return data
        except Exception as exc:
            logger.debug(
                "Failed to read pre-built compliance_scan.json for run %s, "
                "falling through to on-demand scan: %s",
                run_id, exc,
            )

    # On-demand scan: find src/main.py
    main_src: Optional[str] = None
    for candidate in ("src/main.py", "p04_backend/backend_codegen/src/main.py"):
        main_src = safe_fs.read_text_or_none(project_dir, candidate)
        if main_src is not None:
            break

    if main_src is None:
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

    # Scan a private copy of what safe_fs read, so the scanner never opens the sandbox's path.
    with tempfile.TemporaryDirectory(prefix="aether_compliance_") as _tmp:
        _snap = pathlib.Path(_tmp) / "src" / "main.py"
        _snap.parent.mkdir()
        _snap.write_text(main_src, encoding="utf-8")
        scan_result = scan_file(_snap, project_name=_project_name, domain=_domain)

    # Persist the result so subsequent calls are fast (links in project_dir are never followed)
    pdf_path = None
    try:
        scan_rel = pathlib.Path("p06_review_security") / "compliance"
        safe_fs.safe_makedirs(project_dir, scan_rel)
        safe_fs.safe_write_text(project_dir, project_dir / scan_rel / "compliance_scan.json",
                                json.dumps(asdict(scan_result), indent=2, default=str))
        with tempfile.TemporaryDirectory(prefix="aether_compliance_") as _tmp:
            built = generate_pdf(scan_result, pathlib.Path(_tmp) / "compliance_report.pdf")
            safe_fs.safe_write_bytes(project_dir, project_dir / scan_rel / "compliance_report.pdf",
                                     pathlib.Path(built).read_bytes())
        pdf_path = project_dir / scan_rel / "compliance_report.pdf"
    except Exception as exc:
        logger.debug(
            "Failed to persist compliance scan result to disk for run %s: %s", run_id, exc
        )
        pdf_path = None

    result_dict = asdict(scan_result)
    result_dict["pdf_path"] = str(pdf_path) if pdf_path else None
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
        if safe_fs.file_size_or_none(_project_dir, _cand) is not None:   # no links
            _portal_html = str(_cand.relative_to(_project_dir))
            break

    if not _portal_html:
        raise HTTPException(status_code=404, detail="portal_not_generated")

    # Gather deliverables list
    _deliverables = []
    for _phase in ("p10_docs_delivery", "p14_client_portal"):
        for _f in safe_fs.walk_files(_project_dir, _phase):
            _size = safe_fs.file_size_or_none(_project_dir, _f)
            if _size is not None and _f.suffix in (".html", ".pdf", ".zip", ".md", ".json"):
                _deliverables.append({"filename": _f.name, "path": str(_f), "size_bytes": _size})

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
                else ("unavailable" if _council.get("status") == "unavailable"
                      else ("failed" if _council else "pending"))
            ),
        },
        "deliverables": _deliverables,
    }
