"""
AetherOS — Phase Gate Tests
Tests gate pass and gate fail for all 26 phases.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _result(tmp_path, success=True, issues=None, metadata=None, confidence=0.9):
    """Build a TaskResult for gate testing."""
    from aether_os.phases.base import TaskResult
    return TaskResult(
        output_path=str(tmp_path),
        confidence=confidence,
        issues=issues or [],
        metadata=metadata or {},
        success=success,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# P00 — Intake
# ═══════════════════════════════════════════════════════════════════════════════

def test_p00_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p00_intake.gate")
    from aether_os.phases.p00_intake.gate import validate

    intake_data = {
        "raw_text": (
            "Build a SaaS platform for HR teams that includes payroll processing, "
            "leave management, employee onboarding, performance reviews, and analytics dashboards"
        ),
        "structured_requirements": "HR SaaS with payroll, leave management, and analytics",
    }
    out_file = tmp_path / "intake.json"
    out_file.write_text(json.dumps(intake_data))

    from aether_os.phases.base import TaskResult
    result = TaskResult(output_path=str(out_file), confidence=0.9, issues=[], metadata={}, success=True)
    outcome = validate(result)
    assert outcome.passed


def test_p00_gate_fail_short_text(tmp_path):
    pytest.importorskip("aether_os.phases.p00_intake.gate")
    from aether_os.phases.p00_intake.gate import validate

    intake_data = {"raw_text": "No", "structured_requirements": ""}
    out_file = tmp_path / "intake.json"
    out_file.write_text(json.dumps(intake_data))

    from aether_os.phases.base import TaskResult
    result = TaskResult(output_path=str(out_file), confidence=0.3, issues=[], metadata={}, success=True)
    outcome = validate(result)
    assert not outcome.passed


def test_p00_gate_fail_no_output_file(tmp_path):
    pytest.importorskip("aether_os.phases.p00_intake.gate")
    from aether_os.phases.p00_intake.gate import validate

    from aether_os.phases.base import TaskResult
    result = TaskResult(output_path=str(tmp_path / "missing.json"), confidence=0.1, issues=[], metadata={}, success=True)
    outcome = validate(result)
    assert not outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P01 — Requirements
# ═══════════════════════════════════════════════════════════════════════════════

def test_p01_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p01_requirements.gate")
    from aether_os.phases.p01_requirements.gate import validate
    from aether_os.phases.base import TaskResult

    data = {
        "functional_requirements": ["User can login", "User can logout"],
        "acceptance_criteria": ["Login works"],
        "estimated_complexity": "medium",
        "domain": "general"
    }
    req_file = tmp_path / "requirements.json"
    req_file.write_text(json.dumps(data))

    result = TaskResult(output_path=str(req_file), confidence=0.9, success=True)
    outcome = validate(result)
    assert outcome.passed


def test_p01_gate_fail_empty(tmp_path):
    pytest.importorskip("aether_os.phases.p01_requirements.gate")
    from aether_os.phases.p01_requirements.gate import validate
    from aether_os.phases.base import TaskResult

    req_file = tmp_path / "requirements.json"
    req_file.write_text(json.dumps({}))

    result = TaskResult(output_path=str(req_file), confidence=0.3, success=True)
    outcome = validate(result)
    assert not outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P02 — Architecture
# ═══════════════════════════════════════════════════════════════════════════════

def test_p02_gate_pass(tmp_path):
    from aether_os.phases.p02_architecture.gate import validate
    from aether_os.phases.base import TaskResult

    arch = {
        "tech_stack": {
            "backend": "FastAPI", "frontend": "React",
            "database": "PostgreSQL"
        },
        "api_endpoints": [{"method": "GET", "path": "/health"}],
    }
    json_path = tmp_path / "architecture.json"
    json_path.write_text(json.dumps(arch))

    result = TaskResult(
        output_path=str(json_path),
        confidence=0.95, issues=[],
        metadata={"json_path": str(json_path)},
        success=True,
    )
    outcome = validate(result)
    assert outcome.passed


def test_p02_gate_fail_missing_stack(tmp_path):
    from aether_os.phases.p02_architecture.gate import validate
    from aether_os.phases.base import TaskResult

    arch = {"tech_stack": {"backend": "FastAPI"}, "api_endpoints": []}
    json_path = tmp_path / "architecture.json"
    json_path.write_text(json.dumps(arch))

    result = TaskResult(
        output_path=str(json_path), confidence=0.4, issues=[],
        metadata={"json_path": str(json_path)}, success=True,
    )
    outcome = validate(result)
    assert not outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P03 — Scaffolding
# ═══════════════════════════════════════════════════════════════════════════════

def test_p03_gate_pass(tmp_path):
    from aether_os.phases.p03_scaffolding.gate import validate
    from aether_os.phases.base import TaskResult

    proj_dir = tmp_path / "myapp"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("# main")
    (proj_dir / "requirements.txt").write_text("fastapi")
    (proj_dir / ".env.example").write_text("SECRET_KEY=")

    result = TaskResult(
        output_path=str(proj_dir), confidence=0.9, issues=[],
        metadata={"git_init": True}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P04a — Backend Codegen
# ═══════════════════════════════════════════════════════════════════════════════

def test_p04a_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p04a_backend_codegen.gate")
    from aether_os.phases.p04a_backend_codegen.gate import validate
    from aether_os.phases.base import TaskResult

    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\ndef health(): return {}")
    (src / "models.py").write_text("from pydantic import BaseModel\nclass Item(BaseModel): name: str")

    result = TaskResult(
        output_path=str(src), confidence=0.9, issues=[], metadata={}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P04b — UI/UX Design
# ═══════════════════════════════════════════════════════════════════════════════

def test_p04b_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p04b_uiux_design.gate")
    from aether_os.phases.p04b_uiux_design.gate import validate
    from aether_os.phases.base import TaskResult

    design = {
        "pages": [{"name": "Login"}, {"name": "Dashboard"}],
        "design_tokens": {
            "colors": {"primary": "#6366f1"},
            "typography": {"body": "16px"},
            "spacing": {"sm": "8px"},
            "breakpoints": {"md": "768px"},
        },
        "component_inventory": [
            {"name": "Button"}, {"name": "Input"}, {"name": "Card"},
            {"name": "Modal"}, {"name": "Table"},
        ],
    }
    json_path = tmp_path / "components.json"
    json_path.write_text(json.dumps(design))

    result = TaskResult(
        output_path=str(tmp_path / "design.md"), confidence=0.9, issues=[],
        metadata={"json_path": str(json_path)}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P05 — Code Review
# ═══════════════════════════════════════════════════════════════════════════════

def test_p05_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p06_review_security.gate")
    from aether_os.phases.p06_review_security.gate import validate
    from aether_os.phases.base import TaskResult

    report = tmp_path / "review_report.md"
    report.write_text("# Review\nNo critical issues found.\n")

    result = TaskResult(
        output_path=str(report), confidence=0.9, issues=[],
        metadata={"critical": 0, "quality_score": 8}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P06 — Security
# ═══════════════════════════════════════════════════════════════════════════════

def test_p06_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p06_review_security.gate")
    from aether_os.phases.p06_review_security.gate import validate
    from aether_os.phases.base import TaskResult

    report = tmp_path / "security_report.json"
    report.write_text('{"findings": []}')

    result = TaskResult(
        output_path=str(report), confidence=0.9, issues=[],
        metadata={"high_remaining": 0}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# P07a — Unit Testing
# ═══════════════════════════════════════════════════════════════════════════════

def test_p07a_gate_pass():
    pytest.importorskip("aether_os.phases.p07a_unit_testing.gate")
    from aether_os.phases.p07a_unit_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="/tmp/tests", confidence=0.9, issues=[],
        metadata={"pytest_passed": True, "coverage_pct": 80.0, "test_files": 3},
        success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation, Deployment, Monitoring etc.
# ═══════════════════════════════════════════════════════════════════════════════

def test_p09_gate_pass(tmp_path):
    from aether_os.phases.p09_documentation.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path=str(tmp_path), confidence=0.85, issues=[], metadata={}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed

def test_p10_gate_pass(tmp_path):
    from aether_os.phases.p11_deployment.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path=str(tmp_path), confidence=0.9, issues=[], metadata={}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed


# ═══════════════════════════════════════════════════════════════════════════════
# PhaseBase dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

def test_phase_base_importable():
    from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
    assert PhaseBase is not None
    assert TaskResult is not None
    assert GateOutcome is not None


# Later phases (p05 Frontend, p06 Security, p07a Unit Testing, p08 CI/CD,
# p09 Observability, p10 Docs) have been moved to test_phases_later.py to keep
# this file under 400 lines.
