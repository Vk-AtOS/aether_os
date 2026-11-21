"""
AetherOS Build Quality Metrics — v2 Master Implementation.

Real implementation: Scans generated code for Auth, Validation, Seed density,
and Security vulnerabilities as required by the v2 Directive.
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.errors import SandboxViolation
from aether_os.core.quality._project_root import relative_to_root, require_project_root
from aether_os.core.run_app import safe_fs
from aether_os.core.sandbox import phase_exec
from aether_os.core.security.bandit_run import BanditScanError, bandit_args, parse as parse_bandit
from aether_os.core.sandbox.runner import SandboxUnavailable

logger = logging.getLogger(__name__)

# Generated projects are written by sandboxed code, which can plant symlinks: every read and
# walk below goes through safe_fs (never follows a link, never leaves the root).
_SKIP_DIRS = ("__pycache__", "node_modules", ".venv", ".git")


def _read(root: Path, path: Path) -> Optional[str]:
    return safe_fs.read_text_or_none(root, path)


def _files(root: Path, pattern: str, under: Optional[Path] = None) -> List[Path]:
    """Absolute paths of the real files under root[/under] whose name matches the glob pattern.

    root is always the run directory: every component below it is opened with O_NOFOLLOW,
    so a link planted on the way (src_dir itself, or a parent of it) is never followed.
    """
    sub = _rel(root, under) if under is not None else ""
    return [root / rel for rel in safe_fs.walk_files(root, sub, skip_dirs=_SKIP_DIRS)
            if rel.match(pattern)]


_rel = relative_to_root


def _is_file(root: Path, path: Path) -> bool:
    return safe_fs.stat_or_none(root, path) is not None


# ── Route introspection ───────────────────────────────────────────────────────

_HEALTH_PATHS = {"/health", "/metrics", "/ready", "/alive", "/ping", "/healthz"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@dataclass
class RouteInfo:
    path: str
    method: str
    has_auth: bool
    has_input_validation: bool


def _extract_routes(code: str) -> List[RouteInfo]:
    """Parse FastAPI route decorators from Python source code string.

    Detects @app.get/post/... and @router.get/post/... style decorators.
    has_auth = True when any parameter has a Depends(...) default.
    has_input_validation = True when any parameter is annotated with a
    Pydantic BaseModel subclass defined in the same module.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    # Collect all Pydantic model names (classes inheriting BaseModel)
    pydantic_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name == "BaseModel":
                    pydantic_classes.add(node.name)

    routes: List[RouteInfo] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                continue
            method = deco.func.attr.lower()
            if method not in _HTTP_METHODS:
                continue

            # Extract path from first positional arg of the decorator call
            path = ""
            if deco.args and isinstance(deco.args[0], ast.Constant):
                path = str(deco.args[0].value)

            # Detect auth: any param has Depends(...) as its default value
            has_auth = False
            for default in node.args.defaults:
                if isinstance(default, ast.Call):
                    func = default.func
                    func_name = (
                        func.id if isinstance(func, ast.Name)
                        else func.attr if isinstance(func, ast.Attribute)
                        else ""
                    )
                    if func_name == "Depends":
                        has_auth = True
                        break

            # Detect input validation: any param annotated with a known Pydantic model
            has_input_validation = False
            for param in node.args.args:
                if param.arg in ("self", "cls"):
                    continue
                ann = param.annotation
                if ann is not None and isinstance(ann, ast.Name) and ann.id in pydantic_classes:
                    has_input_validation = True
                    break

            routes.append(RouteInfo(
                path=path,
                method=method.upper(),
                has_auth=has_auth,
                has_input_validation=has_input_validation,
            ))

    return routes


# ── QualityScore ──────────────────────────────────────────────────────────────

@dataclass
class QualityScore:
    total: int
    auth_coverage: int          # 0-100: % of non-health routes with auth
    input_validation: int       # 0-100: % of write routes with Pydantic bodies
    test_score: int             # 0-100: based on actual pytest run results
    test_coverage: int          # 0-100: based on test file presence (max 60)
    domain_specificity: int     # 0-100
    seed_data_quality: int      # 0-100
    frontend_complete: int      # 0-100
    docker_valid: int           # 0-100
    security_clean: int         # 0-100
    has_docker: bool = False
    has_env_example: bool = False
    has_readme: bool = False
    has_frontend: bool = False
    has_compliance_report: bool = False
    api_endpoint_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


# ── Individual scorers ────────────────────────────────────────────────────────

def _collect_all_routes(src_dir: Path, root: Path) -> List[RouteInfo]:
    """Read all .py files in src_dir and collect routes. root: the run directory."""
    root = require_project_root(root)
    routes: List[RouteInfo] = []
    for py_file in _files(root, "*.py", under=src_dir):
        code = _read(root, py_file)
        if code is None:
            logger.debug("_collect_all_routes: could not read %s", py_file)
            continue
        routes.extend(_extract_routes(code))
    return routes


def _check_auth_coverage(src_dir: Path, root: Path) -> float:
    """Fraction of non-health routes that have auth (Depends(...))."""
    routes = _collect_all_routes(src_dir, root)
    checkable = [r for r in routes if r.path not in _HEALTH_PATHS]
    if not checkable:
        return 0.0
    protected = sum(1 for r in checkable if r.has_auth)
    return protected / len(checkable)


def _check_input_validation(src_dir: Path, root: Path) -> float:
    """Fraction of write-method routes that have Pydantic body params."""
    routes = _collect_all_routes(src_dir, root)
    write_routes = [r for r in routes if r.method in ("POST", "PUT", "PATCH")]
    if not write_routes:
        return 0.5  # No write routes — give partial credit (no violations)
    validated = sum(1 for r in write_routes if r.has_input_validation)
    return validated / len(write_routes)


def _check_test_coverage(project_dir: Path) -> int:
    """Score 0-60 based on test file presence; real results come from _check_test_score."""
    test_files = (
        _files(project_dir, "test_*.py")
        + _files(project_dir, "*_test.py")
    )
    # Exclude the AetherOS platform's own tests
    test_files = [f for f in test_files if "aether_os/tests" not in str(f)]
    if not test_files:
        return 0
    return 60


def _check_test_score(project_dir: Path) -> float:
    """Score tests based on actual pytest results from p07_testing output."""
    for summary_path in [
        project_dir / "s06_testing" / "unit_testing" / "summary.json",  # where s06 writes it
        project_dir / "p07_testing" / "unit_testing" / "summary.json",
        project_dir / "p07a_unit_testing" / "summary.json",
    ]:
        text = _read(project_dir, summary_path)
        if text is not None:
            try:
                data = json.loads(text)
                passed = data.get("passed", 0)
                failed = data.get("failed", 0)
                if passed + failed == 0:
                    return 0.3 if not data.get("errors") else 0.1
                return min(1.0, passed / (passed + failed))
            except Exception as exc:
                logger.debug("_check_test_score: could not parse %s: %s", summary_path, exc)
    return 0.5


def _check_seed_quality(src_dir: Path, root: Path) -> float:
    """Check if seed.py contains ORM object instantiation."""
    code = _read(require_project_root(root), src_dir / "seed.py")
    if code is None:
        return 0.0
    seeds = re.findall(r"\b[A-Z]\w+\(", code)
    seeds = [s for s in seeds if s not in ("Print(", "Asyncio(", "From(", "Import(")]
    if len(seeds) >= 10:
        return 1.0
    if len(seeds) >= 3:
        return 0.7
    return 0.3


def _check_domain_specificity(src_dir: Path, root: Path) -> float:
    score = 0.0
    root = require_project_root(root)
    frontend_dir = src_dir.parent / "frontend"

    # .tsx since p05 writes typed sources; .jsx kept for projects generated before that.
    widget = (_read(root, frontend_dir / "src" / "components" / "DomainWidget.tsx")
              or _read(root, frontend_dir / "src" / "components" / "DomainWidget.jsx"))
    if widget is not None and len(widget.strip().splitlines()) > 10:
        score += 0.25

    seed = _read(root, src_dir / "seed.py")
    if seed is not None and len(seed.strip().splitlines()) > 20:
        score += 0.25

    dashboard = _read(root, frontend_dir / "src" / "pages" / "Dashboard.tsx")
    if dashboard is not None and "Item 1" not in dashboard and "Test Record" not in dashboard:
        score += 0.25

    pages_dir = frontend_dir / "src" / "pages"
    generic = ("Dashboard.tsx", "Login.tsx", "Register.tsx", "LoginPage.tsx", "NotFoundPage.tsx")
    for name, is_dir in safe_fs.list_dir(root, _rel(root, pages_dir)):
        if is_dir or not name.endswith(".tsx") or name in generic:
            continue
        text = _read(root, pages_dir / name)
        if text is not None and len(text.splitlines()) > 30:
            score += 0.25
            break

    return min(1.0, score)


def _check_frontend_complete(project_dir: Path) -> float:
    frontend_dir = project_dir / "frontend"
    if not safe_fs.is_real_dir(project_dir, frontend_dir):
        p05_dir = project_dir / "p05_frontend" / "frontend"
        if safe_fs.is_real_dir(project_dir, p05_dir):
            frontend_dir = p05_dir
        else:
            return 0.0

    if not _is_file(project_dir, frontend_dir / "package.json"):
        return 0.3

    if not (_is_file(project_dir, frontend_dir / "src" / "main.tsx")
            or _is_file(project_dir, frontend_dir / "src" / "main.jsx")):
        return 0.5

    if _is_file(project_dir, frontend_dir / "dist" / "index.html"):
        return 1.0

    build_status_file = project_dir / "build_status.json"
    status_text = _read(project_dir, build_status_file)
    if status_text is not None:
        try:
            status_data = json.loads(status_text)
            if status_data.get("status") == "done":
                return 1.0
            if status_data.get("status") == "building":
                return 0.7
            if status_data.get("status") == "failed":
                return 0.4
        except Exception as exc:
            logger.debug("_check_frontend_complete: build_status read failed: %s", exc)

    # vite runs the project's own config and plugins: sandbox only, output inside the run dir
    # (the sandbox's only writable place), removed afterwards.
    out_dir = frontend_dir / ".aether_quality_build"
    try:
        result = phase_exec.run_sync(
            ["npx", "vite", "build", "--outDir", str(out_dir), "--logLevel", "silent"],
            cwd=frontend_dir, timeout=120)
        return 1.0 if result.returncode == 0 else 0.6
    except subprocess.TimeoutExpired:
        return 0.6
    except SandboxUnavailable as exc:
        logger.error("_check_frontend_complete: %s", exc)  # not run, so not scored as built
        return 0.6
    except Exception as exc:
        logger.debug("_check_frontend_complete: vite build attempt failed: %s", exc)
        return 0.6
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _check_security_bandit(src_dir: Path) -> float:
    try:
        result = subprocess.run(
            ["bandit", *bandit_args(src_dir)],
            capture_output=True, text=True, timeout=30,
        )
        findings = parse_bandit(result.stdout).get("results", [])
        if not findings:
            return 1.0
        high = sum(1 for r in findings if r.get("issue_severity") == "HIGH")
        return max(0.0, 1.0 - (high * 0.2))
    except BanditScanError as exc:     # bandit ran but gave no report: not "clean" (KAN-69 SC-04)
        logger.warning("_check_security_bandit: no usable bandit report: %s", exc)
        return 0.0
    except Exception as exc:
        logger.debug("_check_security_bandit: bandit scan failed, using default: %s", exc)
        return 0.8


def _find_real_src_dir(project_dir: Path) -> Optional[Path]:
    for candidate in [
        project_dir / "p04_backend" / "backend_codegen" / "src",
        project_dir / "p04a_backend_codegen" / "src",
        project_dir / "p04_backend" / "src",
        project_dir / "src",
    ]:
        if safe_fs.is_real_dir(project_dir, candidate) and _is_file(project_dir, candidate / "main.py"):
            return candidate
    candidates = [
        p.parent for p in _files(project_dir, "main.py")
        if "p03_scaffolding" not in str(p)
    ]
    if candidates:
        candidates.sort(key=lambda p: len(p.parts), reverse=True)
        return candidates[0]
    return None


# ── Public scorer ─────────────────────────────────────────────────────────────

def score_project(project_dir: Path) -> QualityScore:
    """Return a real QualityScore based on AetherOS v2 Master Directive."""
    try:
        project_dir = require_project_root(project_dir)
    except SandboxViolation as exc:     # no usable run directory: nothing is scored, fail closed
        logger.warning("score_project: %s", exc)
        src_dir = None
    else:
        src_dir = _find_real_src_dir(project_dir)
    if src_dir is None:
        return QualityScore(
            total=0, auth_coverage=0, input_validation=0,
            test_score=0, test_coverage=0, domain_specificity=0,
            seed_data_quality=0, frontend_complete=0,
            docker_valid=0, security_clean=0,
        )

    # Compute route-based metrics
    all_routes = _collect_all_routes(src_dir, project_dir)
    checkable_routes = [r for r in all_routes if r.path not in _HEALTH_PATHS]
    write_routes = [r for r in all_routes if r.method in ("POST", "PUT", "PATCH")]

    auth_frac = (
        sum(1 for r in checkable_routes if r.has_auth) / len(checkable_routes)
        if checkable_routes else 0.0
    )
    val_frac = (
        sum(1 for r in write_routes if r.has_input_validation) / len(write_routes)
        if write_routes else 0.5
    )

    # Boolean presence checks
    has_docker = _is_file(project_dir, project_dir / "Dockerfile") or _is_file(project_dir, project_dir / "docker-compose.yml")
    has_env_example = _is_file(project_dir, project_dir / ".env.example")
    has_readme = _is_file(project_dir, project_dir / "README.md")
    has_frontend = _is_file(project_dir, project_dir / "frontend" / "package.json")
    has_compliance_report = _is_file(project_dir, project_dir / "compliance_scan.json")

    # Numeric scores
    test_cov = _check_test_coverage(project_dir)
    test_sc = _check_test_score(project_dir)
    domain_sc = _check_domain_specificity(src_dir, project_dir)
    seed_sc = _check_seed_quality(src_dir, project_dir)
    fe_sc = _check_frontend_complete(project_dir)
    docker_sc = 1.0 if has_docker else 0.0
    sec_sc = _check_security_bandit(src_dir)

    # Weighted formula — main metrics (75 pts max)
    weighted = (
        auth_frac * 0.25
        + val_frac * 0.25
        + (test_cov / 100) * 0.10
        + domain_sc * 0.05
        + seed_sc * 0.05
        + docker_sc * 0.05
        + sec_sc * 0.05
    ) * 100

    # Boolean bonus points (25 pts max)
    bonus = (
        (8 if has_docker else 0)
        + (6 if has_readme else 0)
        + (5 if has_env_example else 0)
        + (6 if has_frontend else 0)
        + (5 if has_compliance_report else 0)
    )

    total = min(100, int(weighted) + bonus)

    return QualityScore(
        total=total,
        auth_coverage=int(auth_frac * 100),
        input_validation=int(val_frac * 100),
        test_score=int(test_sc * 100),
        test_coverage=test_cov,
        domain_specificity=int(domain_sc * 100),
        seed_data_quality=int(seed_sc * 100),
        frontend_complete=int(fe_sc * 100),
        docker_valid=int(docker_sc * 100),
        security_clean=int(sec_sc * 100),
        has_docker=has_docker,
        has_env_example=has_env_example,
        has_readme=has_readme,
        has_frontend=has_frontend,
        has_compliance_report=has_compliance_report,
        api_endpoint_count=len(all_routes),
        details={
            "auth_coverage": auth_frac,
            "input_validation": val_frac,
            "test_score": test_sc,
            "test_coverage": test_cov,
            "domain_specificity": domain_sc,
            "seed_data_quality": seed_sc,
            "frontend_complete": fe_sc,
            "docker_valid": docker_sc,
            "security_clean": sec_sc,
            "routes": len(all_routes),
        },
    )
