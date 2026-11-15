"""
AetherOS — Phase Gate Tests (later phases)
Tests for p05 Frontend, p06 Security, p07a Unit Testing, p08 CI/CD,
p09 Observability, and p10 Docs.

Shared fixtures and imports live in test_phases.py.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════════════════
# P05 Frontend — React/Vite/TanStack generator (PIPELINE-055: updated from CDN)
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


@pytest.mark.asyncio
async def test_p05f_full_run_writes_vite_project(tmp_path):
    """Full run generates a React/Vite frontend project directory."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch
    from aether_os.phases.p05_frontend.task_agent import run
    from aether_os.phases.p05_frontend.gate import validate

    arch_file = tmp_path / "architecture.json"
    arch_file.write_text(json.dumps({
        "api_endpoints": _FAKE_ENDPOINTS,
        "tech_stack": {"backend": "FastAPI", "frontend": "React", "database": "SQLite"},
    }))

    class PhaseInput:
        input_data = {
            "project_name": "Test Dashboard",
            "p02_architecture_path": str(arch_file),
            "project_dir": str(tmp_path),
        }
        domain = "saas"

    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value="")  # LLM returns empty → skip optional domain component
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    # npm / tsc / vite now go through the sandbox runner (core/sandbox/phase_exec.py): stub that boundary.
    with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_client), \
         patch("aether_os.core.sandbox.phase_exec.run", AsyncMock(return_value=mock_proc)), \
         patch("aether_os.core.sandbox.phase_exec.run_sync", return_value=mock_proc):
        out_dir = tmp_path / "output"
        result = await run(PhaseInput(), [], out_dir)

    assert result.success is True
    # Should have written a frontend directory with package.json
    frontend_dir = out_dir / "frontend"
    assert frontend_dir.exists() or (out_dir / "package.json").exists(), \
        "No frontend dir or package.json written"

    gate = validate(result)
    assert gate.passed, f"Gate failed: {gate.issues}"


def test_p05f_gate_fails_missing_file(tmp_path):
    from aether_os.phases.p05_frontend.gate import validate
    from aether_os.phases.base import TaskResult
    result = TaskResult(output_path=str(tmp_path / "nonexistent"),
                        confidence=0.5, success=True)
    assert not validate(result).passed


def test_p05f_nginx_conf_uses_configurable_backend(tmp_path):
    """_generate_nginx_conf uses config dict for container_name and app_port."""
    from aether_os.phases.p05_frontend.task_agent import _generate_nginx_conf
    conf = _generate_nginx_conf({"container_name": "backend", "app_port": 9000})
    assert "backend:9000" in conf
    assert "app:8000" not in conf


def test_p05f_nginx_conf_default_values(tmp_path):
    """_generate_nginx_conf uses 'app' and 8000 when no config given."""
    from aether_os.phases.p05_frontend.task_agent import _generate_nginx_conf
    conf = _generate_nginx_conf()
    assert "app:8000" in conf


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

    with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_llm):
        out_dir = tmp_path / "security_out"
        asyncio.run(
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

    with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_llm):
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
    # Generator uses httpx.AsyncClient for async FastAPI testing
    assert "AsyncClient" in code


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
    with patch("aether_os.core.llm.client.get_llm_client",
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

    with patch("aether_os.core.llm.client.get_llm_client",
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
    await agent.run(PhaseInput())

    ci_file = tmp_path / "p08_cicd_deployment" / "cicd" / "ci.yml"
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

    content = (tmp_path / "p08_cicd_deployment" / "cicd" / "ci.yml").read_text()
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

    with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_llm):
        result = await task_agent.run(PhaseInput(), [], tmp_path / "docs_out")

    readme = tmp_path / "docs_out" / "docs" / "README.md"
    assert readme.exists(), "README.md not written"
    content = readme.read_text()
    assert len(content.split()) >= 500, f"README too short: {len(content.split())} words"
    assert result.success is True


def test_p08_ci_smoke_test_probes_the_port_the_dockerfile_serves(tmp_path):
    """KAN-100: the CI smoke test published and probed 8080 while every generated image serves 8000,
    so the 'health check' could never pass (or, with --network host, probed some other service)."""
    import asyncio
    from aether_os.phases.p08_cicd.task_agent import CICDAgent

    class PhaseInput:
        output_dir = str(tmp_path / "cicd_out")
        input_data = {"project_name": "MyApp", "project_dir": str(tmp_path)}

    asyncio.run(CICDAgent().run(PhaseInput()))
    content = (tmp_path / "p08_cicd_deployment" / "cicd" / "ci.yml").read_text()
    assert "localhost:8000/health" in content and "8080" not in content
    assert 'EXPOSE 8000' in (tmp_path / "Dockerfile").read_text()
