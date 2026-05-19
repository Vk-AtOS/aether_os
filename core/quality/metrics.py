"""
AetherOS Build Quality Metrics.

Scores generated project output across multiple quality dimensions.
Used to track improvement over time and provide buyers with evidence
that AetherOS output quality compounds across builds.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class RouteInfo:
    path: str
    method: str
    has_auth: bool = False
    has_input_validation: bool = False


@dataclass
class QualityScore:
    total: int                   # 0-100
    auth_coverage: int           # % of endpoints with auth
    input_validation: int        # % of write endpoints with validation
    test_coverage: int           # 0=no tests, 50=tests exist, 100=tests pass
    has_docker: bool
    has_env_example: bool
    has_readme: bool
    has_frontend: bool
    has_compliance_report: bool
    api_endpoint_count: int
    details: dict = field(default_factory=dict)


# Patterns used to detect route decorators in generated FastAPI code
_ROUTE_RE = re.compile(
    r'@app\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Patterns that indicate JWT/auth dependency injection
_AUTH_DEP_RE = re.compile(
    r'Depends\s*\(\s*(get_current_user|require_auth|verify_token|authenticate|jwt_required)',
    re.IGNORECASE,
)
# Pydantic BaseModel body parameter pattern (input validation)
_PYDANTIC_PARAM_RE = re.compile(
    r':\s*[A-Z][A-Za-z0-9_]*\s*(?:,|\))',
)
# Inline bearer / Authorization header check
_INLINE_AUTH_RE = re.compile(
    r'Authorization|Bearer|verify_token|decode_token|jwt\.decode',
    re.IGNORECASE,
)


def _extract_routes(source: str) -> List[RouteInfo]:
    """
    Parse FastAPI route decorators from source code.

    For each route, detect whether:
      - auth is enforced (Depends on a known auth callable, or inline token check in func body)
      - input is validated via a Pydantic model parameter

    Returns a list of RouteInfo objects.
    """
    routes: List[RouteInfo] = []

    # Split on route decorator boundaries so we can inspect each function block
    # We find each @app.<method>(...) and then grab the next ~30 lines as function context
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = _ROUTE_RE.search(line)
        if not m:
            continue
        method = m.group(1).upper()
        path = m.group(2)

        # Gather the function signature + body (next 40 lines)
        context_lines = lines[i: min(i + 40, len(lines))]
        context = "\n".join(context_lines)

        # Auth detection
        has_auth = bool(_AUTH_DEP_RE.search(context)) or bool(_INLINE_AUTH_RE.search(context))

        # Input validation: POST/PUT/PATCH with a Pydantic model typed parameter
        has_validation = False
        if method in ("POST", "PUT", "PATCH"):
            # Find the async def / def line within context
            sig_match = re.search(r'(?:async\s+)?def\s+\w+\s*\(([^)]{0,300})\)', context, re.DOTALL)
            if sig_match:
                sig = sig_match.group(1)
                # Look for BaseModel subclass annotations (capitalised type, not built-ins)
                builtins = {"str", "int", "float", "bool", "list", "dict", "bytes", "Any",
                            "Optional", "Dict", "List", "Request", "HTTPException", "Response"}
                for param_m in re.finditer(r':\s*([A-Z][A-Za-z0-9_]*)', sig):
                    typ = param_m.group(1)
                    if typ not in builtins:
                        has_validation = True
                        break

        routes.append(RouteInfo(
            path=path,
            method=method,
            has_auth=has_auth,
            has_input_validation=has_validation,
        ))

    return routes


def score_project(project_dir: Path) -> QualityScore:
    """Score a generated project directory across quality dimensions."""
    details: dict = {}

    # ── Locate main.py ────────────────────────────────────────────────────────
    main_py: Optional[Path] = None
    for candidate in [project_dir / "src" / "main.py", project_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break

    routes: List[RouteInfo] = []

    # ── Auth coverage ─────────────────────────────────────────────────────────
    auth_coverage = 0
    api_count = 0
    if main_py:
        try:
            source = main_py.read_text(encoding="utf-8", errors="replace")
            routes = _extract_routes(source)
            PUBLIC = {
                "/health", "/docs", "/redoc", "/openapi.json",
                "/auth/login", "/auth/register", "/",
            }
            data_routes = [r for r in routes if r.path not in PUBLIC]
            api_count = len(routes)
            details["routes"] = api_count
            if data_routes:
                protected = sum(1 for r in data_routes if r.has_auth)
                auth_coverage = int(protected / len(data_routes) * 100)
                details["auth_protected"] = protected
                details["auth_total"] = len(data_routes)
            else:
                auth_coverage = 100  # no data routes → trivially covered
                details["auth_protected"] = 0
                details["auth_total"] = 0
        except Exception as exc:
            details["auth_error"] = str(exc)
            auth_coverage = 50  # benefit of the doubt if we can't parse

    # ── Input validation ──────────────────────────────────────────────────────
    validation_score = 0
    if main_py:
        try:
            write_routes = [r for r in routes if r.method in ("POST", "PUT", "PATCH")]
            if write_routes:
                validated = sum(1 for r in write_routes if r.has_input_validation)
                validation_score = int(validated / len(write_routes) * 100)
                details["validated_write_routes"] = validated
                details["total_write_routes"] = len(write_routes)
            else:
                validation_score = 100  # no write routes → trivially valid
        except Exception as exc:
            details["validation_error"] = str(exc)
            validation_score = 50

    # ── Test coverage ─────────────────────────────────────────────────────────
    test_score = 0
    test_files = list(project_dir.rglob("test_*.py")) + list(project_dir.rglob("*_test.py"))
    # Exclude __pycache__
    test_files = [f for f in test_files if "__pycache__" not in str(f)]
    details["test_files"] = len(test_files)
    if test_files:
        test_score = 75 if len(test_files) > 1 else 50

    # ── File presence checks ──────────────────────────────────────────────────
    has_docker = (
        (project_dir / "Dockerfile").exists()
        or (project_dir / "docker-compose.yml").exists()
    )
    has_env_example = (project_dir / ".env.example").exists()
    has_readme = (project_dir / "README.md").exists()
    has_frontend = (
        (project_dir / "frontend").is_dir()
        or (project_dir / "frontend" / "package.json").exists()
    )
    has_compliance = bool(
        list(project_dir.rglob("compliance_report.pdf"))
        or list(project_dir.rglob("compliance_scan.json"))
    )

    details["has_docker"] = has_docker
    details["has_env_example"] = has_env_example
    details["has_readme"] = has_readme
    details["has_frontend"] = has_frontend
    details["has_compliance"] = has_compliance

    # ── Weighted total ────────────────────────────────────────────────────────
    total = int(
        auth_coverage * 0.30
        + validation_score * 0.20
        + test_score * 0.20
        + (100 if has_docker else 0) * 0.10
        + (100 if has_env_example else 0) * 0.05
        + (100 if has_readme else 0) * 0.05
        + (100 if has_frontend else 0) * 0.05
        + (100 if has_compliance else 0) * 0.05
    )

    return QualityScore(
        total=total,
        auth_coverage=auth_coverage,
        input_validation=validation_score,
        test_coverage=test_score,
        has_docker=has_docker,
        has_env_example=has_env_example,
        has_readme=has_readme,
        has_frontend=has_frontend,
        has_compliance_report=has_compliance,
        api_endpoint_count=api_count,
        details=details,
    )
