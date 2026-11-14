"""P04a Gate — validates backend code quality and production standards."""
from __future__ import annotations
import re
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    p = Path(result.output_path or "")
    if not p.exists():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Backend output directory not found"])

    py_files = list(p.rglob("*.py")) if p.is_dir() else ([p] if p.suffix == ".py" else [])
    if not py_files:
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["No Python files found in backend output"])

    issues = []
    warnings = []

    # Hard failures. The gate used to append only to `warnings`, so it passed whatever it found (KAN-169).
    src = p / "src"
    for required in ("main.py", "models.py", "schemas.py", "auth.py", "database.py", "seed.py", "routers/crud.py"):
        if not (src / required).is_file():
            issues.append(f"Required file src/{required} is missing")
    for f in sorted(src.rglob("*.py")) if src.is_dir() else []:
        try:
            compile(f.read_text(), str(f), "exec")
        except (SyntaxError, ValueError) as exc:
            issues.append(f"{f.relative_to(p)} does not compile: {exc}")
        if re.search(r"^\s*(?:from|import)\s+aether_os\b", f.read_text(), re.MULTILINE):
            issues.append(f"{f.relative_to(p)} imports the AetherOS platform package, which the customer's app does not have")

    # Check for /health endpoint
    main_py = p / "src" / "main.py"
    if main_py.exists():
        content = main_py.read_text()
        if "/health" not in content:
            warnings.append("No /health endpoint in main.py — add for load balancer checks")
        if "/ready" not in content:
            warnings.append("No /ready endpoint — add for Kubernetes readiness probes")
        if "X-Request-ID" not in content and "request_id" not in content:
            warnings.append("No X-Request-ID middleware — add for distributed tracing")

    # Check crud.py for pagination
    crud_files = list(p.rglob("crud.py"))
    for crud_file in crud_files:
        crud_content = crud_file.read_text()
        # List endpoints should have skip/limit or page/size
        list_routes = re.findall(r'@\w+\.get\([^)]+\)[^@]+def \w+list[^(]*\([^)]*\)',
                                  crud_content, re.IGNORECASE | re.DOTALL)
        get_routes = re.findall(r'@\w+\.get\(["\'][^"\']*["\'][^)]*\)', crud_content)
        if get_routes and "skip" not in crud_content and "limit" not in crud_content:
            warnings.append(f"{crud_file.name}: list endpoints may lack pagination (skip/limit)")

    # Check for connection pooling in database.py
    db_py = p / "src" / "database.py"
    if db_py.exists():
        db_content = db_py.read_text()
        if "pool_size" not in db_content:
            warnings.append("database.py missing pool_size config — add for production")

    passed = len(issues) == 0
    confidence = 0.9 if (passed and not warnings) else (0.75 if passed else 0.3)
    return GateOutcome(passed=passed, confidence=confidence, issues=issues + warnings)
