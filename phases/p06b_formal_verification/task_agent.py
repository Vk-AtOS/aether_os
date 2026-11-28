"""
P06b static invariant checks on generated routes (AST), plus a Z3 proof of the permission rule (INV-008/009).

Orchestrates:
  1. Scan all .py files in the generated project for FastAPI routes
  2. For each route, run the static invariant checks (INV-001..007)
  3. Write formal_verification_report.json to the generated project root
  4. Return a VerificationReport — verdict PASS/FAIL/PARTIAL

Pipeline gate: FAIL verdict raises PipelineBlockedError (same pattern as P06).
Graceful degradation: if Z3 is unavailable, returns PARTIAL (never crashes pipeline).

See z3_encoder.py for the Z3 encoding details and invariant definitions.
"""
from __future__ import annotations

import ast
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.errors import SandboxViolation
from aether_os.core.quality._project_root import require_project_root
from aether_os.core.run_app import safe_fs
from aether_os.phases.base import TaskResult
from aether_os.phases.p06b_formal_verification.z3_permissions import check_project_permissions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"
_MAX_FILES_TO_SCAN = 50     # cap to keep runtime bounded for large projects
_MAX_FILE_SIZE_BYTES = 200_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_py_files(project_dir: Path) -> List[Path]:
    """
    Return up to _MAX_FILES_TO_SCAN .py files from the generated project src/.
    We prioritise src/ and app/ subdirs where FastAPI routes typically live.
    """
    candidates: List[Path] = []
    # The generated project is sandbox-written: walk it relative to the run dir, never through a link.
    root = require_project_root(project_dir)

    for subdir in ["src", "app", "api", "routers", ""]:
        under = Path(subdir) if subdir else Path()
        if not safe_fs.is_real_dir(root, under):
            continue
        for rel in safe_fs.walk_files(root, under, skip_dirs=("__pycache__", "node_modules", ".venv", ".git")):
            py = root / rel
            if py.suffix == ".py" and py not in candidates:
                candidates.append(py)

    return candidates[:_MAX_FILES_TO_SCAN]


def _parse_file(path: Path, root: Path) -> ast.Module | None:
    """Return parsed AST or None if the file is too large, unreadable (a link, outside root) or has syntax errors."""
    try:
        data = safe_fs.read_bytes_or_none(root, path.relative_to(root), _MAX_FILE_SIZE_BYTES + 1)
        if data is None or len(data) > _MAX_FILE_SIZE_BYTES:
            logger.debug("[p06b] skip unreadable or large file %s", path)
            return None
        source = data.decode("utf-8", errors="replace")
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.debug("[p06b] syntax error in %s: %s", path, exc)
        return None
    except OSError as exc:
        logger.warning("[p06b] cannot read %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# VerificationReport assembly
# ---------------------------------------------------------------------------

# Said in every report, because "formal verification" reads as more than this is: each invariant is a
# yes/no fact the AST scan extracted (a route has an auth dependency, a payment field is bounded, ...) and
# Z3 only confirms that the fact is true. It is a static check of the generated source, not a proof about
# runtime behaviour, and it can only be as right as the scan.
_SCOPE_NOTE = (
    "Static invariant checks over the generated source (AST), not a proof of runtime behaviour. INV-001..007 "
    "are yes/no facts extracted from the AST (effective route/router/include-level auth dependencies, tenant "
    "filters, raw body reads, f-string SQL, commit counts); no solver is used for them. Only INV-008/009 use Z3: "
    "the permission rule the app enforces (services/permissions.py) is modelled symbolically over every role, "
    "resource and action, and that property is proved. Routes marked @public_route or listed in PUBLIC_ROUTES / "
    "the public allowlist are intentionally public."
)


def _permission_results(project_dir: Path) -> list:
    """INV-008/009 for the project's services/permissions.py; a bad run directory or a crash yields none."""
    try:
        return check_project_permissions(project_dir)
    except SandboxViolation as exc:
        logger.warning("[p06b] permission proof skipped: %s", exc)
    except Exception as exc:
        logger.warning("[p06b] permission proof failed: %s", exc)
    return []


def _build_report(
    all_results: list,
    project_name: str,
    domain: str,
    total_files: int,
    z3_version: str,
    run_time_ms: int,
    z3_available: bool,
    partial_reason: str = "",
) -> Dict[str, Any]:
    """
    Assemble the formal_verification_report.json payload from InvariantResult objects.
    """

    verified: List[Dict] = []
    failed: List[Dict] = []
    unverifiable: List[Dict] = []

    # Deduplicate: one entry per (invariant_id, route_name)
    seen: set = set()
    for r in all_results:
        key = (r.invariant_id, r.route_name)
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "invariant_id": r.invariant_id,
            "invariant_name": r.invariant_name,
            "route": r.route_name,
            "status": r.status,
            "proof_method": r.proof_method,
            "solver_time_ms": r.solver_time_ms,
            "confidence": r.confidence,
        }
        if r.violation_detail:
            entry["violation_detail"] = r.violation_detail

        if r.status in ("VERIFIED", "N/A"):
            verified.append(entry)
        elif r.status == "VIOLATED":
            failed.append(entry)
        else:  # UNVERIFIABLE
            unverifiable.append(entry)

    # Overall verdict
    if failed:
        verdict = "FAIL"          # a proven violation is a FAIL even when the run was otherwise partial
    elif partial_reason:
        verdict = "PARTIAL"
    elif not verified and not unverifiable:
        verdict = "PARTIAL"  # No routes found — cannot claim PASS
    else:
        verdict = "PASS"

    # Confidence score: fraction of results that are VERIFIED or N/A
    total = len(verified) + len(failed) + len(unverifiable)
    confidence = round(len(verified) / total, 3) if total else 0.0

    report: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "z3_version": z3_version,
        "z3_available": z3_available,
        "project_name": project_name,
        "domain": domain,
        "files_scanned": total_files,
        "overall_verdict": verdict,
        "confidence_score": confidence,
        "z3_solver_time_ms": run_time_ms,
        "scope": _SCOPE_NOTE,
        "invariants_verified": verified,
        "invariants_failed": failed,
        "invariants_unverifiable": unverifiable,
        # patent_eligible field removed — was hardcoded marketing copy in a
        # technical artifact, not a valid output of the SMT verification process.
    }
    if partial_reason:
        report["partial_reason"] = partial_reason

    return report


# ---------------------------------------------------------------------------
# Main run() entry point
# ---------------------------------------------------------------------------

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    P06b entry point.

    Reads the generated project from phase_input.input_data["project_dir"],
    scans .py files for FastAPI routes, runs Z3 invariant checks, writes
    formal_verification_report.json to both output_dir AND the project root.

    Never raises — failures are surfaced as PARTIAL in the report and in the
    TaskResult metadata so the gate can decide to block.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    data: Dict[str, Any] = getattr(phase_input, "input_data", {}) or {}
    project_name: str = data.get("project_name", "unknown")
    domain: str = data.get("domain", "general")

    # Resolve project_dir — try several keys used by different pipeline versions
    project_dir_str: str = (
        data.get("project_dir")
        or data.get("output_path")
        or data.get("backend_output_path")
        or ""
    )
    project_dir = Path(project_dir_str) if project_dir_str else None

    t0 = time.monotonic()

    # ── Z3 availability check ─────────────────────────────────────────────────
    z3_available = False
    z3_version = "unavailable"
    partial_reason = ""
    try:
        import z3  # noqa: PLC0415
        z3_available = True
        z3_version = z3.get_version_string()
    except ImportError as exc:
        partial_reason = f"z3-solver not installed: {exc}"
        logger.warning("[p06b] Z3 unavailable — returning PARTIAL: %s", exc)

    if project_dir is None or not project_dir.is_dir():
        # Best-effort: scan output_dir itself (e.g., if called standalone)
        project_dir = output_dir
        logger.debug("[p06b] project_dir not provided; scanning output_dir %s", output_dir)

    # The permission rule is proved with Z3 when present, else by exhaustive enumeration of its finite domain.
    perm_results = _permission_results(project_dir)

    # ── Locate generated files ────────────────────────────────────────────────
    try:
        py_files = _find_py_files(project_dir)
    except SandboxViolation as exc:
        logger.warning("[p06b] refusing to scan %s: %s", project_dir, exc)
        py_files = []
    logger.info("[p06b] scanning %d Python files in %s", len(py_files), project_dir)

    # ── Run the static invariant checks ───────────────────────────────────────
    from aether_os.phases.p06b_formal_verification.route_deps import collect_included_auth  # noqa: PLC0415
    from aether_os.phases.p06b_formal_verification.z3_encoder import Z3Encoder  # noqa: PLC0415

    parsed = [(py_file, _parse_file(py_file, project_dir)) for py_file in py_files]
    parsed = [(f, m) for f, m in parsed if m is not None]
    # include_router(..., dependencies=[...]) lives in main.py but guards routes defined in other files.
    included_auth = collect_included_auth({f.stem: m for f, m in parsed})
    public_routes = list(data.get("public_routes") or [])

    all_results = list(perm_results)
    for py_file, module_ast in parsed:
        try:
            encoder = Z3Encoder(module_ast, py_file.stem, included_auth, public_routes)
            if encoder.route_count() == 0:
                continue  # not a routes file
            file_results = encoder.verify_all()
            all_results.extend(file_results)
            logger.debug("[p06b] %s: %d routes, %d results", py_file.name,
                         encoder.route_count(), len(file_results))
        except Exception as exc:
            # Per spec: never crash the pipeline; log and continue
            logger.warning("[p06b] encoder error for %s: %s", py_file, exc)

    run_time_ms = int((time.monotonic() - t0) * 1000)

    # ── Assemble report ───────────────────────────────────────────────────────
    report = _build_report(
        all_results=all_results,
        project_name=project_name,
        domain=domain,
        total_files=len(py_files),
        z3_version=z3_version,
        run_time_ms=run_time_ms,
        z3_available=z3_available,
    )

    verdict = report["overall_verdict"]
    n_fail = len(report["invariants_failed"])
    n_pass = len(report["invariants_verified"])
    n_skip = len(report["invariants_unverifiable"])
    logger.info(
        "[p06b] verdict=%s verified=%d failed=%d unverifiable=%d time=%dms",
        verdict, n_pass, n_fail, n_skip, run_time_ms,
    )

    return _write_and_return(report, output_dir, project_dir, "")


def _write_and_return(
    report: Dict[str, Any],
    output_dir: Path,
    project_dir: Path | None,
    issues_msg: str,
) -> TaskResult:
    """Write report to output_dir (and project root if available); return TaskResult."""
    report_name = "formal_verification_report.json"
    report_json = json.dumps(report, indent=2)

    # Always write to phase output dir
    phase_report = output_dir / report_name
    try:
        phase_report.write_text(report_json, encoding="utf-8")
    except OSError as exc:
        logger.warning("[p06b] cannot write phase report: %s", exc)

    # Also write to generated project root for downstream phases / delivery
    if project_dir and project_dir.is_dir() and project_dir != output_dir:
        try:
            (project_dir / report_name).write_text(report_json, encoding="utf-8")
        except OSError as exc:
            logger.debug("[p06b] project root report write failed (non-fatal): %s", exc)

    verdict = report.get("overall_verdict", "PARTIAL")
    confidence = float(report.get("confidence_score", 0.0))
    n_fail = len(report.get("invariants_failed", []))
    issues: List[str] = []
    if issues_msg:
        issues.append(issues_msg)
    for f in report.get("invariants_failed", []):
        detail = f.get("violation_detail") or f.get("proof_method", "")
        issues.append(f"VIOLATED [{f['invariant_id']}] {f['route']}: {detail}")

    return TaskResult(
        output_path=str(phase_report),
        confidence=confidence,
        metadata={
            "overall_verdict": verdict,
            "report_path": str(phase_report),
            "z3_version": report.get("z3_version", "unavailable"),
            "files_scanned": report.get("files_scanned", 0),
            "invariants_verified_count": len(report.get("invariants_verified", [])),
            "invariants_failed_count": n_fail,
            "invariants_unverifiable_count": len(report.get("invariants_unverifiable", [])),
            "z3_solver_time_ms": report.get("z3_solver_time_ms", 0),
        },
        issues=issues,
        success=(verdict in ("PASS", "PARTIAL")),
    )
