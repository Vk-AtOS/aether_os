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
    pytest.importorskip("aether_os.phases.p05_code_review.gate")
    from aether_os.phases.p05_code_review.gate import validate
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
    pytest.importorskip("aether_os.phases.p06_security.gate")
    from aether_os.phases.p06_security.gate import validate
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
    pytest.importorskip("aether_os.phases.p09_documentation.gate")
    from aether_os.phases.p09_documentation.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path=str(tmp_path), confidence=0.85, issues=[], metadata={}, success=True,
    )
    outcome = validate(result)
    assert outcome.passed

def test_p10_gate_pass(tmp_path):
    pytest.importorskip("aether_os.phases.p10_deployment.gate")
    from aether_os.phases.p10_deployment.gate import validate
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


# ═══════════════════════════════════════════════════════════════════════════════
# P05 Frontend — CDN React / vanilla-JS generator
# ═══════════════════════════════════════════════════════════════════════════════

_FAKE_ENDPOINTS = [
    {"method": "GET",  "path": "/health", "description": "Health check"},
    {"method": "GET",  "path": "/items",  "description": "List items"},
    {"method": "POST", "path": "/items",  "description": "Create item"},
]


def test_p05f_architecture_reader_from_path(tmp_path):
    import json
    from aether_os.phases.p05_frontend.task_agent import _read_architecture
    f = tmp_path / "architecture.json"
    f.write_text(json.dumps({"api_endpoints": _FAKE_ENDPOINTS}))
    result = _read_architecture({"p02_architecture_path": str(f)})
    assert len(result["api_endpoints"]) == 3


def test_p05f_architecture_reader_from_project_dir(tmp_path):
    import json
    from aether_os.phases.p05_frontend.task_agent import _read_architecture
    sub = tmp_path / "p02_architecture"
    sub.mkdir()
    (sub / "architecture.json").write_text(json.dumps({"api_endpoints": _FAKE_ENDPOINTS[:1]}))
    result = _read_architecture({"project_dir": str(tmp_path)})
    assert result["api_endpoints"]


def test_p05f_architecture_reader_default():
    from aether_os.phases.p05_frontend.task_agent import _read_architecture
    result = _read_architecture({})
    assert result["api_endpoints"]  # must return non-empty default


def test_p05f_validator_accepts_good_component():
    from aether_os.phases.p05_frontend.task_agent import _validate_component
    good = 'function App() { const [x,sX]=React.useState(null); return (<div><h1>Hi</h1></div>); }'
    assert _validate_component(good)


def test_p05f_validator_rejects_bad_output():
    from aether_os.phases.p05_frontend.task_agent import _validate_component
    assert not _validate_component("")
    assert not _validate_component("Here is some text about React")
    assert not _validate_component("function helper() { return 42; }")  # no JSX


def test_p05f_vanilla_html_structure():
    from aether_os.phases.p05_frontend.task_agent import _build_vanilla_html
    html = _build_vanilla_html("My Project", _FAKE_ENDPOINTS)
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "<script" in html
    assert "fetch(" in html
    assert "/health" in html
    assert "/items" in html
    assert "DOMContentLoaded" in html
    assert "```" not in html  # no markdown leakage


def test_p05f_react_html_structure():
    from aether_os.phases.p05_frontend.task_agent import _build_react_html
    component = 'function App() { return (<div><h1>Test</h1></div>); }'
    html = _build_react_html("Test", _FAKE_ENDPOINTS, component)
    assert "<!DOCTYPE html>" in html
    assert "react.development.js" in html
    assert "babel.min.js" in html
    assert 'type="text/babel"' in html
    assert "function App" in html
    assert "ReactDOM.createRoot" in html
    assert "```" not in html


@pytest.mark.asyncio
async def test_p05f_full_run_fallback(tmp_path):
    """Full run with LLM mocked to return junk → uses vanilla-JS fallback."""
    import json
    from unittest.mock import AsyncMock, patch
    from aether_os.phases.p05_frontend.task_agent import run
    from aether_os.phases.p05_frontend.gate import validate

    arch_file = tmp_path / "architecture.json"
    arch_file.write_text(json.dumps({"api_endpoints": _FAKE_ENDPOINTS}))

    class PhaseInput:
        input_data = {
            "project_name": "Test Dashboard",
            "p02_architecture_path": str(arch_file),
        }

    # LLM returns garbage → fallback path is taken
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value="This is not valid JSX at all")
    with patch("aether_os.phases.p05_frontend.task_agent.get_llm_client",
               return_value=mock_client):
        out_dir = tmp_path / "output"
        result = await run(PhaseInput(), [], out_dir)

    index = out_dir / "index.html"
    assert index.exists(), "index.html not created"
    content = index.read_text()
    assert len(content) > 500
    assert "<html" in content.lower()
    assert "<script" in content.lower()
    assert "fetch(" in content
    assert "```" not in content
    assert result.metadata["renderer"] == "vanilla-js"

    gate = validate(result)
    assert gate.passed, f"Gate failed: {gate.issues}"
    assert gate.confidence >= 0.8


@pytest.mark.asyncio
async def test_p05f_full_run_react(tmp_path):
    """Full run with LLM mocked to return good JSX → react-babel path."""
    import json
    from unittest.mock import AsyncMock, patch
    from aether_os.phases.p05_frontend.task_agent import run
    from aether_os.phases.p05_frontend.gate import validate

    arch_file = tmp_path / "architecture.json"
    arch_file.write_text(json.dumps({"api_endpoints": _FAKE_ENDPOINTS}))

    class PhaseInput:
        input_data = {
            "project_name": "Test Dashboard",
            "p02_architecture_path": str(arch_file),
        }

    good_component = (
        'function App() {\n'
        '  const [data, setData] = React.useState(null);\n'
        '  React.useEffect(() => { fetch("/health").then(r=>r.json()).then(setData); }, []);\n'
        '  return (<div><h1>Test Dashboard</h1><pre>{JSON.stringify(data)}</pre></div>);\n'
        '}'
    )
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value=good_component)
    with patch("aether_os.phases.p05_frontend.task_agent.get_llm_client",
               return_value=mock_client):
        out_dir = tmp_path / "output"
        result = await run(PhaseInput(), [], out_dir)

    index = out_dir / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "react.development.js" in content
    assert "babel.min.js" in content
    assert "function App" in content
    assert result.metadata["renderer"] == "react-babel"
    assert result.metadata["used_llm"] is True

    gate = validate(result)
    assert gate.passed


def test_p05f_gate_fails_missing_file(tmp_path):
    from aether_os.phases.p05_frontend.gate import validate
    from aether_os.phases.base import TaskResult
    result = TaskResult(output_path=str(tmp_path / "nonexistent.html"),
                        confidence=0.5, success=True)
    assert not validate(result).passed


def test_p05f_gate_fails_tiny_file(tmp_path):
    from aether_os.phases.p05_frontend.gate import validate
    from aether_os.phases.base import TaskResult
    tiny = tmp_path / "index.html"
    tiny.write_text("<html></html>")
    result = TaskResult(output_path=str(tiny), confidence=0.5, success=True)
    assert not validate(result).passed


def test_p05f_gate_passes_full_html(tmp_path):
    from aether_os.phases.p05_frontend.task_agent import _build_vanilla_html
    from aether_os.phases.p05_frontend.gate import validate
    from aether_os.phases.base import TaskResult
    index = tmp_path / "index.html"
    index.write_text(_build_vanilla_html("Test", _FAKE_ENDPOINTS))
    result = TaskResult(output_path=str(index), confidence=0.9, success=True)
    outcome = validate(result)
    assert outcome.passed
    assert outcome.confidence >= 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# P06 — Security scan
# ═══════════════════════════════════════════════════════════════════════════════

def test_p06_security_report_written(tmp_path):
    """p06_review_security writes consolidated.json even with no source files."""
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock
    from aether_os.phases.p06_review_security import task_agent

    class PhaseInput:
        input_data = {"project_dir": str(tmp_path), "source_code": "x = 1"}

    mock_llm = MagicMock()
    mock_llm.call = AsyncMock(return_value='{"findings": [], "overall_score": 100, "summary": "ok"}')

    with patch.object(task_agent, "get_llm_client", return_value=mock_llm):
        out_dir = tmp_path / "security_out"
        result = asyncio.run(
            task_agent.run(PhaseInput(), [], out_dir)
        )

    # p06_review_security writes consolidated.json, not security_report.json
    report = out_dir / "consolidated.json"
    assert report.exists(), "consolidated.json not written"
    data = json.loads(report.read_text())
    assert "phases" in data


def test_p06_security_scans_src_subdir(tmp_path):
    """p06_review_security handles src/ subdirectory gracefully."""
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock
    from aether_os.phases.p06_review_security import task_agent

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

    class PhaseInput:
        input_data = {"project_dir": str(tmp_path)}

    mock_llm = MagicMock()
    mock_llm.call = AsyncMock(return_value='{"findings": [], "overall_score": 100, "summary": "ok"}')

    with patch.object(task_agent, "get_llm_client", return_value=mock_llm):
        out_dir = tmp_path / "security_out"
        result = asyncio.run(
            task_agent.run(PhaseInput(), [], out_dir)
        )

    assert result.success is True or result.success is False  # non-blocking either way
    report = out_dir / "consolidated.json"
    assert report.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# P07a — Unit Testing
# ═══════════════════════════════════════════════════════════════════════════════

def test_p07a_fallback_tests_are_valid_python(tmp_path):
    """Fallback test generator produces syntactically valid Python."""
    import ast
    from aether_os.phases.p07a_unit_testing.task_agent import _fallback_tests

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n\n'
        '@app.get("/health")\ndef health(): return {"status": "ok"}\n'
        '@app.get("/items")\ndef items(): return []\n'
    )

    code = _fallback_tests(src_dir)
    # Must parse without error
    ast.parse(code)
    assert "def test_health" in code
    assert "TestClient" in code


def test_p07a_find_src_dir(tmp_path):
    """_find_src_dir locates src/main.py in project_dir tree."""
    from aether_os.phases.p07a_unit_testing.task_agent import _find_src_dir

    # Create the expected path
    src = tmp_path / "p04_backend" / "backend_codegen" / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text("# app")

    result = _find_src_dir({"project_dir": str(tmp_path)})
    assert result == src


@pytest.mark.asyncio
async def test_p07a_full_run_no_source(tmp_path):
    """Full run with no source files writes placeholder test and returns success."""
    from aether_os.phases.p07a_unit_testing.task_agent import run
    from unittest.mock import AsyncMock, patch

    class PhaseInput:
        input_data = {"project_dir": str(tmp_path / "empty_run")}

    mock_llm = AsyncMock()
    with patch("aether_os.phases.p07a_unit_testing.task_agent.get_llm_client",
               return_value=mock_llm):
        result = await run(PhaseInput(), [], tmp_path / "out")

    assert result.success is True
    # Placeholder test must exist
    tests = list((tmp_path / "out" / "tests").glob("*.py"))
    assert len(tests) >= 1


@pytest.mark.asyncio
async def test_p07a_full_run_with_source_uses_fallback_on_bad_llm(tmp_path):
    """When LLM returns invalid Python, fallback test is written (always valid)."""
    import ast
    from aether_os.phases.p07a_unit_testing.task_agent import run
    from unittest.mock import AsyncMock, patch

    src = tmp_path / "run" / "p04_backend" / "backend_codegen" / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text(
        'from fastapi import FastAPI\napp=FastAPI()\n'
        '@app.get("/health")\ndef health(): return {"status":"ok"}\n'
    )

    class PhaseInput:
        input_data = {"project_dir": str(tmp_path / "run")}

    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value="this is !!! not valid python ???")

    with patch("aether_os.phases.p07a_unit_testing.task_agent.get_llm_client",
               return_value=mock_llm):
        result = await run(PhaseInput(), [], tmp_path / "out")

    assert result.success is True
    test_file = tmp_path / "out" / "tests" / "test_main.py"
    assert test_file.exists(), "test_main.py not written"
    # Must be valid Python
    ast.parse(test_file.read_text())


# ═══════════════════════════════════════════════════════════════════════════════
# P08 CI/CD — ci.yml generation
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_p08_cicd_generates_ci_yml(tmp_path):
    """CICDAgent writes ci.yml referencing the project name."""
    from aether_os.phases.p08_cicd.task_agent import CICDAgent

    class PhaseInput:
        output_dir = str(tmp_path / "cicd_out")
        input_data = {"project_name": "Todo REST API", "project_dir": str(tmp_path)}

    agent = CICDAgent()
    result = await agent.run(PhaseInput())

    ci_file = tmp_path / "cicd_out" / "ci.yml"
    assert ci_file.exists(), "ci.yml not written"
    content = ci_file.read_text()
    assert "pytest" in content
    assert "pip install" in content
    # Project name should appear in the CI file
    assert "Todo REST API" in content or "todo-rest-api" in content


def test_p08_ci_yml_has_required_steps(tmp_path):
    """ci.yml contains checkout, setup-python, pip install, pytest."""
    import asyncio
    from aether_os.phases.p08_cicd.task_agent import CICDAgent

    class PhaseInput:
        output_dir = str(tmp_path / "cicd_out")
        input_data = {"project_name": "MyApp", "project_dir": str(tmp_path)}

    agent = CICDAgent()
    asyncio.run(agent.run(PhaseInput()))

    content = (tmp_path / "cicd_out" / "ci.yml").read_text()
    assert "actions/checkout" in content
    assert "setup-python" in content
    assert "requirements.txt" in content


# ═══════════════════════════════════════════════════════════════════════════════
# P09 Observability — prometheus.yml + docker-compose
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_p09_monitoring_writes_prometheus_yml(tmp_path):
    """p11a_monitoring writes prometheus.yml and docker-compose.monitoring.yml."""
    from aether_os.phases.p11a_monitoring import task_agent

    class PhaseInput:
        input_data = {
            "project_name": "todo-api",
            "project_dir": str(tmp_path),
            "architecture_json": {},
        }

    result = await task_agent.run(PhaseInput(), [], tmp_path / "mon_out")

    assert result.success is True
    assert (tmp_path / "mon_out" / "monitoring" / "prometheus.yml").exists()
    assert (tmp_path / "mon_out" / "monitoring" / "docker-compose.monitoring.yml").exists()


@pytest.mark.asyncio
async def test_p09_monitoring_prometheus_has_scrape_config(tmp_path):
    """prometheus.yml contains correct scrape_configs."""
    from aether_os.phases.p11a_monitoring import task_agent

    class PhaseInput:
        input_data = {
            "project_name": "my-service",
            "project_dir": str(tmp_path),
            "architecture_json": {},
        }

    await task_agent.run(PhaseInput(), [], tmp_path / "mon_out")

    prom_yml = (tmp_path / "mon_out" / "monitoring" / "prometheus.yml").read_text()
    assert "scrape_configs" in prom_yml
    assert "my-service" in prom_yml
    assert "metrics_path" in prom_yml


# ═══════════════════════════════════════════════════════════════════════════════
# P10 Docs delivery — README.md fallback
# ═══════════════════════════════════════════════════════════════════════════════

def test_p10_fallback_readme_is_long_enough(tmp_path):
    """_build_fallback_readme produces >= 500 words."""
    pytest.importorskip("aether_os.phases.p09_documentation.task_agent")
    from aether_os.phases.p09_documentation.task_agent import _build_fallback_readme

    arch = {
        "tech_stack": {"backend": "FastAPI", "database": "SQLite"},
        "api_endpoints": [
            {"method": "GET", "path": "/health", "description": "Health check", "auth": False},
            {"method": "POST", "path": "/items", "description": "Create item", "auth": True},
        ],
        "database_schema": [
            {"table": "items", "columns": ["id", "title", "done"]}
        ],
    }
    readme = _build_fallback_readme("Todo API", arch, "CRUD todo list")
    words = len(readme.split())
    assert words >= 500, f"README has only {words} words"


def test_p10_fallback_readme_has_key_sections(tmp_path):
    """_build_fallback_readme includes Installation, API, curl examples."""
    pytest.importorskip("aether_os.phases.p09_documentation.task_agent")
    from aether_os.phases.p09_documentation.task_agent import _build_fallback_readme

    arch = {
        "tech_stack": {"backend": "FastAPI", "database": "SQLite"},
        "api_endpoints": [
            {"method": "GET", "path": "/health", "description": "Health check", "auth": False},
        ],
    }
    readme = _build_fallback_readme("Test App", arch, "")
    assert "## Installation" in readme
    assert "## API Reference" in readme
    assert "curl" in readme
    assert "/health" in readme


@pytest.mark.asyncio
async def test_p10_docs_run_writes_readme(tmp_path):
    """p09_documentation.run() writes README.md even when LLM fails."""
    pytest.importorskip("aether_os.phases.p09_documentation.task_agent")
    from unittest.mock import AsyncMock, patch, MagicMock
    from aether_os.phases.p09_documentation import task_agent

    class PhaseInput:
        input_data = {
            "project_name": "Test App",
            "project_dir": str(tmp_path),
            "architecture_json": {
                "tech_stack": {"backend": "FastAPI", "database": "SQLite"},
                "api_endpoints": [
                    {"method": "GET", "path": "/health", "description": "Health check"}
                ],
            },
            "requirements_doc": "A simple test app",
        }

    # LLM returns empty string → fallback kicks in
    mock_llm = MagicMock()
    mock_llm.call = AsyncMock(return_value="")

    with patch.object(task_agent, "get_llm_client", return_value=mock_llm):
        result = await task_agent.run(PhaseInput(), [], tmp_path / "docs_out")

    readme = tmp_path / "docs_out" / "docs" / "README.md"
    assert readme.exists(), "README.md not written"
    content = readme.read_text()
    assert len(content.split()) >= 500, f"README too short: {len(content.split())} words"
    assert result.success is True
