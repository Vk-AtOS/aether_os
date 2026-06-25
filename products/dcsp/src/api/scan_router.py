"""
Proactive repository scan endpoint.

Clones the repo, runs syntax/import checks on every source file,
then feeds each discovered error through the standard repair pipeline.
Results are stored as RepairJob records and appear in the Patches queue.
"""

from __future__ import annotations

import ast
import logging
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db
from src.repo import REPO_MANAGER, GLOBAL_INDEXER
from src.pipeline import run_repair
from src.dfle.call_graph import CallGraph
from src.db.job_repo import save_job
from src.api.state import add_job_to_history

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scan", tags=["scan"])


class ScanRequest(BaseModel):
    repo_name: str


class ScanIssue(BaseModel):
    file: str
    line: int | None = None
    error_type: str
    message: str
    patch_diff: str = ""
    confidence: float = 0.0
    fixed: bool = False


class ScanResponse(BaseModel):
    repo_name: str
    scanned_at: str
    total_files: int
    issues_found: int
    issues: list[ScanIssue]
    status: str


def _build_synthetic_log(file_path: str, error_type: str, message: str, line: int | None) -> str:
    """Build a traceback-style CI log from a static analysis finding."""
    loc = f", line {line}" if line else ""
    return (
        f"Traceback (most recent call last):\n"
        f'  File "{file_path}"{loc}\n'
        f"{error_type}: {message}\n"
    )


def _scan_python_file(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rel = str(path.relative_to(repo_root))

    # 1. Syntax check
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        ast.parse(source)
    except SyntaxError as e:
        issues.append({"file": rel, "line": e.lineno, "error_type": "SyntaxError", "message": str(e.msg)})
        return issues  # can't check imports if syntax is broken

    # 2. Import check via subprocess (isolated from current process)
    try:
        result = subprocess.run(
            ["python3", "-c", f"import py_compile; py_compile.compile('{path}', doraise=True)"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            issues.append({"file": rel, "line": None, "error_type": "CompileError", "message": err[:300]})
    except Exception as e:
        logger.warning("Compile check failed for %s: %s", rel, e)

    return issues


def _run_scan(repo_name: str) -> ScanResponse:
    """Clone repo, check all Python files, run repair pipeline for each issue."""
    scanned_at = datetime.utcnow().isoformat()

    try:
        repo_url = f"https://github.com/{repo_name}.git"
        repo_root_str = REPO_MANAGER.clone_or_pull(repo_url)
        repo_root = Path(repo_root_str)
        GLOBAL_INDEXER.index_repository(repo_root_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not clone repository: {e}")

    # Collect Python files (skip venv, node_modules, .git)
    skip_dirs = {".git", "venv", ".venv", "node_modules", "__pycache__", ".tox", "dist", "build"}
    py_files = [
        p for p in repo_root.rglob("*.py")
        if not any(s in p.parts for s in skip_dirs)
    ]

    raw_issues: list[dict[str, Any]] = []
    for f in py_files:
        raw_issues.extend(_scan_python_file(f, repo_root))

    total_files = len(py_files)
    scan_issues: list[ScanIssue] = []

    for raw in raw_issues:
        log = _build_synthetic_log(
            str(repo_root / raw["file"]), raw["error_type"], raw["message"], raw.get("line")
        )
        try:
            result = run_repair(
                log_content=log,
                root_dir=repo_root_str,
                historical_records=[],
                ast_index=GLOBAL_INDEXER,
                call_graph=CallGraph(),
            )
            patch = result.patch_diff if result.success else ""
            confidence = result.confidence if result.success else 0.0
            fixed = result.success

            # Persist as a RepairJob so it appears in the Patches queue
            if result.success or result.escalated:
                job_data = {
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.utcnow().isoformat(),
                    "repo_name": repo_name,
                    "branch": "main",
                    "ci_system": "scan",
                    "detected_language": result.detected_language,
                    "success": result.success,
                    "confidence": result.confidence,
                    "escalated": result.escalated,
                    "explanation": f"[Scan] {raw['error_type']}: {raw['message'][:100]}",
                    "patch_diff": result.patch_diff,
                    "slm_generated": result.slm_generated,
                    "violations": result.violations,
                    "source": result.source,
                    "fingerprint": result.fingerprint,
                    "sandbox_result": getattr(result, "sandbox_result", None),
                }
                add_job_to_history(job_data)
                try:
                    from src.database import SessionLocal
                    s = SessionLocal()
                    try:
                        save_job(s, job_data)
                    finally:
                        s.close()
                except Exception as db_err:
                    logger.warning("Scan: could not persist job: %s", db_err)
        except Exception as e:
            logger.warning("Scan repair failed for %s: %s", raw["file"], e)
            patch, confidence, fixed = "", 0.0, False

        scan_issues.append(ScanIssue(
            file=raw["file"],
            line=raw.get("line"),
            error_type=raw["error_type"],
            message=raw["message"],
            patch_diff=patch,
            confidence=confidence,
            fixed=fixed,
        ))

    return ScanResponse(
        repo_name=repo_name,
        scanned_at=scanned_at,
        total_files=total_files,
        issues_found=len(scan_issues),
        issues=scan_issues,
        status="complete",
    )


@router.post("", response_model=ScanResponse)
async def scan_repository(req: ScanRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> ScanResponse:
    """Synchronously scan a repository for startup-blocking errors."""
    if not req.repo_name or "/" not in req.repo_name:
        raise HTTPException(status_code=400, detail="repo_name must be in owner/repo format")
    try:
        return _run_scan(req.repo_name)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Scan failed for %s", req.repo_name)
        raise HTTPException(status_code=500, detail=str(e))
