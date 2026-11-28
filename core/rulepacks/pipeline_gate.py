"""The rule-pack gate of a run (KAN-243): design, security and prod-readiness checks on what the customer receives.

    result = await run_rulepacks_gate(ws, out_dir, project_name, public_routes=spec_public_routes(context))
    result.passed / result.reason / result.to_metadata()

1. The clean export of the run (core/project_export: the same tree the download and the GitHub push build) is scanned
   with scan_project and the spec's public routes.
2. Blocking findings (high/critical) in MODEL-WRITTEN files (core/rulepacks/provenance.py) go back to the model through
   the shared repair path (core/codegen/patching: numbered source, verified find/replace patches, .py files must
   compile), with repair_prompt() as the error text. At most MAX_ROUNDS rounds; the export is rebuilt and re-scanned
   after each.
3. A blocking finding in a TEMPLATE file (anything a generator wrote without a model, the files the export itself adds,
   and project-level findings) is a platform bug: it is never repaired or suppressed here, the gate fails and the
   reason names the rule id and the file.

The full report is written to `rulepacks_report.json`; its summary goes into the stage metadata.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from aether_os.core.codegen.patching import MAX_SOURCE_CHARS, apply_verified, build_prompt, request_patches
from aether_os.core.project_export import ExportError, exported_tree, locate_backend, locate_frontend
from aether_os.core.rulepacks.base import BLOCKING, Finding
from aether_os.core.rulepacks.provenance import load_model_files
from aether_os.core.rulepacks.report import Report, repair_prompt, scan_project

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
REPORT_FILE = "rulepacks_report.json"
# Routes the generated auth router serves without a token on purpose: sign-in, sign-up, refresh (it reads the HttpOnly
# refresh cookie) and logout (it only clears that cookie, and must work after the access token expired). Mirrors
# phases/p04a_backend_codegen/templates_auth.py; tests/test_kan243_rulepacks_gate.py scans that template with it.
PLATFORM_PUBLIC_ROUTES = ("POST /auth/login", "POST /auth/register", "POST /auth/refresh", "POST /auth/logout",
                          "/health", "/ready")

# repair(app_root, rel_path, errors) -> True when a patch was applied. The default asks the model (patching.py).
RepairFn = Callable[[Path, str, str], Awaitable[bool]]


def spec_public_routes(context: dict) -> list[str]:
    """The platform's own public routes plus the ones the spec declares (context["public_routes"], e.g.
    ["GET /products/*"] for a public catalogue)."""
    declared = context.get("public_routes") if isinstance(context, dict) else None
    extra = [str(r) for r in declared if isinstance(r, str) and r.strip()] if isinstance(declared, (list, tuple)) else []
    return list(PLATFORM_PUBLIC_ROUTES) + extra


@dataclass
class GateResult:
    ran: bool
    passed: bool
    reason: str = ""
    report: dict = field(default_factory=dict)
    rounds: int = 0
    repaired: list[str] = field(default_factory=list)
    report_path: str = ""

    def to_metadata(self) -> dict:
        return {"ran": self.ran, "passed": self.passed, "blocking_reason": self.reason or None,
                "counts": self.report.get("counts", {}), "counts_by_pack": self.report.get("counts_by_pack", {}),
                "repair_rounds": self.rounds, "repaired_files": self.repaired, "report_path": self.report_path or None}


class _Layout:
    """Maps export paths (backend/..., frontend/...) back to the run workspace and to who wrote each file."""

    def __init__(self, ws: Path):
        self.apps: dict[str, Path] = {}
        for prefix, rel in (("backend/", locate_backend(ws)), ("frontend/", locate_frontend(ws))):
            if rel is not None:
                self.apps[prefix] = (ws / rel) if rel else ws
        self.model = {prefix: load_model_files(root) for prefix, root in self.apps.items()}

    def locate(self, export_rel: str) -> Optional[tuple[Path, str]]:
        """(app root in the workspace, path inside it) for a model-written file, None for a template file."""
        for prefix, root in self.apps.items():
            if export_rel.startswith(prefix):
                inner = export_rel[len(prefix):]
                return (root, inner) if inner in self.model[prefix] else None
        return None


def _scan(ws: Path, project_name: str, public_routes: list[str]) -> Report:
    with exported_tree(ws, project_name) as (root, _manifest):
        report = scan_project(root, public_routes=public_routes)
    report.root = "<export>"     # the temp folder is gone; paths in the findings are export-relative
    return report


async def model_repair(app_root: Path, rel: str, errors: str) -> bool:
    """One repair of one model-written file through the shared patch path; only that file may change."""
    target = (app_root / rel).resolve()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("rulepacks gate: cannot read %s for repair: %s", target, e)
        return False
    numbered = "\n".join(f"{n}| {ln[:300]}" for n, ln in enumerate(text.splitlines(), 1))[:MAX_SOURCE_CHARS]
    prompt = build_prompt("You are fixing a generated application so it passes its security, design and "
                          "production-readiness checks.", errors, f"--- {rel}\n{numbered}", example=rel)
    report = await apply_verified(app_root, await request_patches(prompt, "[rulepacks] repair"),
                                  lambda p: p.resolve() == target, "[rulepacks] repair")
    return report.applied > 0


def _blocking(report: Report) -> list[Finding]:
    return [f for f in report.findings if f.severity in BLOCKING]


def _describe(findings: list[Finding], limit: int = 8) -> str:
    parts = [f"{f.rule_id} in {f.file or 'the project'}{':' + str(f.line) if f.line else ''} ({f.message})"
             for f in findings[:limit]]
    return "; ".join(parts) + (f" (+{len(findings) - limit} more)" if len(findings) > limit else "")


async def run_rulepacks_gate(ws: Path, out_dir: Path, project_name: str = "app",
                             public_routes: Optional[list[str]] = None, repair: RepairFn = model_repair,
                             max_rounds: int = MAX_ROUNDS) -> GateResult:
    """Scan the run's export, repair model-written blocking files, and decide. Never raises."""
    ws, out_dir = Path(ws), Path(out_dir)
    routes = list(public_routes) if public_routes is not None else list(PLATFORM_PUBLIC_ROUTES)
    try:
        layout = _Layout(ws)
        report = await asyncio.to_thread(_scan, ws, project_name, routes)
    except ExportError as e:
        # The export check of the stage reports this; the rule packs cannot say anything about a tree that does not exist.
        logger.warning("rulepacks gate: not run, the run cannot be exported: %s", e)
        return GateResult(ran=False, passed=True, reason="")
    except Exception as e:
        logger.warning("rulepacks gate: scan crashed: %s", e)
        return GateResult(ran=False, passed=False, reason=f"rule-pack scan crashed: {e}")

    rounds, repaired = 0, []
    while rounds < max_rounds:
        fixable = {}
        for f in _blocking(report):
            loc = layout.locate(f.file) if f.file else None
            if loc is not None:
                fixable.setdefault(f.file, loc)
        if not fixable:
            break
        rounds += 1
        for export_rel, (app_root, inner) in fixable.items():
            mine = [dataclasses.replace(f, file=inner) for f in report.findings if f.file == export_rel]
            if await repair(app_root, inner, repair_prompt(mine, inner)):
                repaired.append(export_rel)
        report = await asyncio.to_thread(_scan, ws, project_name, routes)

    blocking = _blocking(report)
    template = [f for f in blocking if not f.file or layout.locate(f.file) is None]
    model = [f for f in blocking if f not in template]
    reasons = []
    if template:
        reasons.append("platform bug, a template file breaks a blocking rule (fix the generator, never the output): "
                       + _describe(template))
    if model:
        reasons.append(f"model-written file(s) still break a blocking rule after {rounds} repair round(s): "
                       + _describe(model))
    data = report.to_dict()
    data.update(repair_rounds=rounds, repaired_files=sorted(set(repaired)),
                template_blocking=[f.to_dict() for f in template], model_blocking=[f.to_dict() for f in model])
    path = out_dir / REPORT_FILE
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("rulepacks gate: cannot write %s: %s", path, e)
    result = GateResult(ran=True, passed=not reasons, reason="; ".join(reasons), report=data, rounds=rounds,
                        repaired=sorted(set(repaired)), report_path=str(path))
    logger.info("rulepacks gate: %s (counts %s, %d repair round(s))", "passed" if result.passed else "BLOCKED",
                data["counts"], rounds)
    return result


async def run_stage_gate(phase_input: Any, out_dir: Path, issues: list) -> dict:
    """The gate for a pipeline stage (s11): resolves the run workspace and the spec's public routes, appends the
    blocking reason to `issues`, returns the metadata summary (stored as metadata["rulepacks"])."""
    data = getattr(phase_input, "input_data", None) or {}
    ws = Path(data.get("project_dir") or "")
    if not str(data.get("project_dir") or "") or not ws.is_dir():
        from aether_os.core.projects import get_project_manager   # lazy: the project manager pulls in the DB layer
        ws = get_project_manager().get_project_dir(phase_input.project_id)
    result = await run_rulepacks_gate(ws, out_dir, str(data.get("project_name") or "app"), spec_public_routes(data))
    if result.reason:
        issues.append(f"Rule packs: {result.reason}")
    return result.to_metadata()


def blocks_gate(validate: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Decorator for a stage's validate_gate: fail the gate when metadata["rulepacks"] carries a blocking reason, after
    whatever the stage's own gate decided (kept as a wrapper so the stage's gate code is not touched)."""
    @functools.wraps(validate)
    async def wrapper(self, result, phase_input):
        gate = await validate(self, result, phase_input)
        reason = ((getattr(result, "metadata", None) or {}).get("rulepacks") or {}).get("blocking_reason")
        if not reason:
            return gate
        return dataclasses.replace(gate, passed=False, issues=[f"rule packs: {reason}"] + list(gate.issues or []))
    return wrapper
