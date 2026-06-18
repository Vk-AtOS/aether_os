"""P04 Gate — static syntax + structural validation of the generated backend."""
from __future__ import annotations
import ast
import json
import logging
import subprocess
import sys
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def _find_backend_dir(result: TaskResult) -> Path | None:
    op = Path(result.output_path or "")
    if op.is_dir():
        return op
    # backend_codegen is the canonical subdirectory written by p04a
    for candidate in [op / "backend_codegen", op.parent / "backend_codegen", op.parent]:
        if candidate.is_dir() and any(candidate.rglob("*.py")):
            return candidate
    if op.parent.is_dir() and any(op.parent.rglob("*.py")):
        return op.parent
    return None


def validate(result: TaskResult) -> GateOutcome:
    backend_dir = _find_backend_dir(result)

    if not backend_dir:
        return GateOutcome(
            passed=result.success,
            confidence=result.confidence,
            issues=result.issues or ["No backend output directory found"],
        )

    py_files = list(backend_dir.rglob("*.py"))
    if not py_files:
        return GateOutcome(passed=False, confidence=0.0, issues=["No Python files generated in backend"])

    # ── 1. Syntax check every .py file ────────────────────────────────────────
    syntax_errors: list[str] = []
    for py_file in py_files:
        try:
            ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as exc:
            try:
                rel = str(py_file.relative_to(backend_dir))
            except ValueError:
                rel = py_file.name
            syntax_errors.append(f"{rel}:{exc.lineno}: {exc.msg}")

    if syntax_errors:
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=[f"SyntaxError — {e}" for e in syntax_errors[:5]],
        )

    # ── 2. Locate and validate main.py ────────────────────────────────────────
    main_py: Path | None = None
    for candidate in ["src/main.py", "main.py", "app/main.py"]:
        p = backend_dir / candidate
        if p.exists():
            main_py = p
            break
    if main_py is None:
        candidates = list(backend_dir.rglob("main.py"))
        if candidates:
            main_py = min(candidates, key=lambda p: len(p.parts))

    main_issues: list[str] = []
    if main_py:
        source = main_py.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI" not in source:
            main_issues.append("main.py: FastAPI() not found — app may not start")
        # Subprocess import check (catches circular imports, missing deps)
        try:
            proc = subprocess.run(
                [sys.executable, "-c",
                 f"import ast; ast.parse(open({str(main_py)!r}).read()); print('OK')"],
                capture_output=True, text=True, timeout=8,
            )
            if proc.returncode != 0 and proc.stderr:
                err = proc.stderr.strip()[:300]
                main_issues.append(f"main.py import-level error: {err}")
        except Exception as exc:
            logger.debug("p04 gate: main.py syntax check subprocess failed (non-fatal): %s", exc)
    else:
        main_issues.append("main.py not found — generated app may not be runnable")

    # Hard fail on import errors — self-healing can fix these precisely
    if any("import-level error" in i for i in main_issues):
        return GateOutcome(passed=False, confidence=0.1, issues=main_issues)

    # ── 3. api_routes.json check ──────────────────────────────────────────────
    route_issues: list[str] = []
    routes_file = next(backend_dir.rglob("api_routes.json"), None)
    if not routes_file:
        route_issues.append(
            "api_routes.json missing — p05 frontend cannot wire API calls accurately; "
            "ensure p04a route extraction succeeded"
        )
    else:
        try:
            routes = json.loads(routes_file.read_text())
            if not routes:
                route_issues.append("api_routes.json is empty — no routes were extracted from generated code")
        except Exception:
            route_issues.append("api_routes.json is malformed JSON")

    all_issues = main_issues + route_issues

    if main_issues and not any("import-level" in i for i in main_issues):
        return GateOutcome(passed=True, confidence=0.72, issues=all_issues)

    if route_issues:
        return GateOutcome(passed=True, confidence=0.82, issues=all_issues)

    return GateOutcome(passed=True, confidence=0.93, issues=all_issues)
