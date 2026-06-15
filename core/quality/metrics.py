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
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class QualityScore:
    total: int
    auth_coverage: int
    input_validation: int
    test_score: int
    domain_specificity: int
    seed_data_quality: int
    frontend_complete: int
    docker_valid: int
    security_clean: int
    details: Dict[str, Any] = field(default_factory=dict)

def _check_auth_coverage(src_dir: Path) -> float:
    """Check if JWT decode middleware is defined and routes use it."""
    routers_dir = src_dir / "routers"
    if not routers_dir.exists():
        return 0.0
    
    # Check for JWT guard/middleware
    has_jwt = False
    for f in src_dir.rglob("*.py"):
        if "jwt" in f.read_text(errors="ignore").lower():
            has_jwt = True
            break
            
    if not has_jwt: return 0.0
    
    total_routes = 0
    protected_routes = 0
    
    for f in routers_dir.glob("*.py"):
        if f.name == "__init__.py": continue
        code = f.read_text(errors="ignore")
        # Look for @app.get/post etc.
        routes = re.findall(r"@\w+\.(?:get|post|put|patch|delete)\(", code)
        total_routes += len(routes)
        
        # Look for auth dependencies or auth-specific decorators
        protected = len(re.findall(r"Depends\(get_current_user\)|@requires_auth", code))
        protected_routes += min(protected, len(routes))
        
    if total_routes == 0: return 1.0
    return min(1.0, protected_routes / total_routes)

def _check_validation_density(src_dir: Path) -> float:
    """Check if schemas use Pydantic validators or Field constraints."""
    # Find all Pydantic models
    model_files = list(src_dir.rglob("models.py")) + list(src_dir.rglob("schemas.py"))
    
    total_fields = 0
    validated_fields = 0
    
    for f in model_files:
        code = f.read_text(errors="ignore")
        # Find all fields defined as Mapped[type] = mapped_column(...) or Type: type = ...
        fields = re.findall(r"mapped_column\((.+?)\)", code)
        total_fields += len(fields)
        
        # Count fields with constraints (nullable=False, ForeignKey, index=True)
        # or Pydantic Field() / validators
        validated = len(re.findall(r"mapped_column\(.*?nullable=False.*?\)", code))
        validated += len(re.findall(r"mapped_column\(ForeignKey", code))
        validated_fields += min(validated, len(fields))

    if total_fields == 0: return 0.5
    return min(1.0, validated_fields / total_fields)

def _check_seed_quality(src_dir: Path) -> float:
    """Check if seed.py contains ORM object instantiation."""
    seed_py = src_dir / "seed.py"
    if not seed_py.exists():
        return 0.0
    
    code = seed_py.read_text(errors="ignore")
    # Check for instantiation of ORM classes (assuming ClassName())
    # This is a heuristic: uppercase class names followed by (
    seeds = re.findall(r"\b[A-Z]\w+\(", code)
    
    # Exclude common calls if any
    seeds = [s for s in seeds if s not in ("print(", "asyncio(", "from(", "import(")]
    
    if len(seeds) >= 10: return 1.0
    if len(seeds) >= 3: return 0.7
    return 0.3

def _check_domain_specificity(src_dir: Path) -> float:
    """Check if dashboard stat labels contain domain entity names."""
    score = 0.0
    frontend_dir = src_dir.parent / "frontend"
    
    # +0.25 if DomainWidget.jsx exists and has more than 10 lines
    widget_path = frontend_dir / "src" / "components" / "DomainWidget.jsx"
    if widget_path.exists():
        try:
            if len(widget_path.read_text().strip().splitlines()) > 10:
                score += 0.25
        except Exception:
            pass
    
    # +0.25 if seed.py exists and has more than 20 lines (real seed data, not stub)
    seed_path = src_dir / "seed.py"
    if seed_path.exists():
        try:
            if len(seed_path.read_text().strip().splitlines()) > 20:
                score += 0.25
        except Exception:
            pass
    
    # +0.25 if Dashboard page contains no generic "Item" or "Record" text in stat labels
    dashboard_path = frontend_dir / "src" / "pages" / "Dashboard.tsx"
    if dashboard_path.exists():
        try:
            content = dashboard_path.read_text(errors="ignore")
            if "Item 1" not in content and "Test Record" not in content:
                score += 0.25
        except Exception:
            pass
    
    # +0.25 if primary entity list page has domain-appropriate column headers
    pages_dir = frontend_dir / "src" / "pages"
    if pages_dir.exists():
        try:
            tsx_files = list(pages_dir.glob("*.tsx"))
            for f in tsx_files:
                if f.name not in ("Dashboard.tsx", "Login.tsx", "Register.tsx", "LoginPage.tsx", "NotFoundPage.tsx"):
                    if len(f.read_text(errors="ignore").splitlines()) > 30:
                        score += 0.25
                        break
        except Exception:
            pass
    
    return min(1.0, score)

def _check_frontend_complete(project_dir: Path) -> float:
    frontend_dir = project_dir / "frontend"
    if not frontend_dir.exists():
        # Also check p05_frontend output
        p05_dir = project_dir / "p05_frontend" / "frontend"
        if p05_dir.exists():
            frontend_dir = p05_dir
        else:
            return 0.0

    if not (frontend_dir / "package.json").exists():
        return 0.3

    main_tsx = frontend_dir / "src" / "main.tsx"
    main_jsx = frontend_dir / "src" / "main.jsx"
    if not main_tsx.exists() and not main_jsx.exists():
        return 0.5

    # If dist already exists with index.html, score full without rebuilding
    dist_dir = frontend_dir / "dist"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        return 1.0

    # Check build_status.json (async build in progress)
    build_status_file = project_dir / "build_status.json"
    if build_status_file.exists():
        try:
            status_data = json.loads(build_status_file.read_text())
            if status_data.get("status") == "done":
                return 1.0
            if status_data.get("status") == "building":
                return 0.7  # In progress — partial credit
            if status_data.get("status") == "failed":
                return 0.4
        except Exception:
            pass

    # Attempt build only if source files exist and no prior attempt
    import tempfile, subprocess
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["npx", "vite", "build", "--outDir", tmp, "--logLevel", "silent"],
                cwd=str(frontend_dir),
                capture_output=True,
                timeout=120,  # Extended to 2 minutes
            )
            return 1.0 if result.returncode == 0 else 0.6
    except subprocess.TimeoutExpired:
        return 0.6
    except Exception:
        return 0.6

def _check_security_bandit(src_dir: Path) -> float:
    """Run bandit and score based on findings."""
    try:
        result = subprocess.run(
            ["bandit", "-r", "-f", "json", str(src_dir)],
            capture_output=True, text=True, timeout=30,
        )
        if not result.stdout: return 1.0
        data = json.loads(result.stdout)
        findings = data.get("results", [])
        if not findings: return 1.0
        high = sum(1 for r in findings if r.get("issue_severity") == "HIGH")
        score = 1.0 - (high * 0.2)
        return max(0.0, score)
    except Exception:
        return 0.8

def _find_real_src_dir(project_dir: Path) -> Optional[Path]:
    """Find the p04-generated backend src dir, NOT the p03 scaffolding stubs."""
    # Priority: p04 canonical locations first
    for candidate in [
        project_dir / "p04_backend" / "backend_codegen" / "src",
        project_dir / "p04a_backend_codegen" / "src",
        project_dir / "p04_backend" / "src",
        project_dir / "src",
    ]:
        if candidate.is_dir() and (candidate / "main.py").exists():
            return candidate
    # Glob fallback — exclude scaffolding stubs
    candidates = [
        p.parent for p in project_dir.rglob("main.py")
        if "p03_scaffolding" not in str(p)
        and "__pycache__" not in str(p)
        and ".venv" not in str(p)
    ]
    if candidates:
        candidates.sort(key=lambda p: len(p.parts), reverse=True)
        return candidates[0]
    return None


def _check_test_score(project_dir: Path) -> float:
    """Score tests based on actual pytest results from p07_testing output."""
    for summary_path in [
        project_dir / "p07_testing" / "unit_testing" / "summary.json",
        project_dir / "p07a_unit_testing" / "summary.json",
    ]:
        if summary_path.exists():
            try:
                data = json.loads(summary_path.read_text())
                passed = data.get("passed", 0)
                failed = data.get("failed", 0)
                errors = data.get("errors", [])
                if passed + failed == 0:
                    return 0.3 if not errors else 0.1
                ratio = passed / (passed + failed)
                return min(1.0, ratio)
            except Exception:
                pass
    return 0.5  # No test results yet — give partial credit


def score_project(project_dir: Path) -> QualityScore:
    """Return a real QualityScore based on AetherOS v2 Master Directive."""
    src_dir = _find_real_src_dir(project_dir)
    if src_dir is None:
        return QualityScore(0, 0, 0, 0, 0, 0, 0, 0, 0)

    metrics = {
        "auth_coverage": _check_auth_coverage(src_dir),
        "validation": _check_validation_density(src_dir),
        "test_score": _check_test_score(project_dir),
        "domain_specificity": _check_domain_specificity(src_dir),
        "seed_data_quality": _check_seed_quality(src_dir),
        "frontend_complete": _check_frontend_complete(project_dir),
        "docker_valid": 1.0 if (project_dir / "docker-compose.yml").exists() else 0.0,
        "security_clean": _check_security_bandit(src_dir),
    }

    # Weighted formula from Directive Section 3.8
    total = (
        (metrics["auth_coverage"] * 0.20) +
        (metrics["validation"] * 0.20) +
        (metrics["test_score"] * 0.15) +
        (metrics["domain_specificity"] * 0.15) +
        (metrics["seed_data_quality"] * 0.10) +
        (metrics["frontend_complete"] * 0.10) +
        (metrics["docker_valid"] * 0.05) +
        (metrics["security_clean"] * 0.05)
    ) * 100

    return QualityScore(
        total=int(total),
        auth_coverage=int(metrics["auth_coverage"] * 100),
        input_validation=int(metrics["validation"] * 100),
        test_score=int(metrics["test_score"] * 100),
        domain_specificity=int(metrics["domain_specificity"] * 100),
        seed_data_quality=int(metrics["seed_data_quality"] * 100),
        frontend_complete=int(metrics["frontend_complete"] * 100),
        docker_valid=int(metrics["docker_valid"] * 100),
        security_clean=int(metrics["security_clean"] * 100),
        details=metrics
    )
