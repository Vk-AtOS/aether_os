"""P08 Task Agent — CI/CD Repair or Proactive Scan."""
from __future__ import annotations
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

class CICDAgent:
    async def run(self, phase_input: Any) -> dict:
        context = phase_input.input_data
        # phase_input.output_dir is usually something like .../project_id/p08_cicd
        project_dir = Path(phase_input.output_dir).parent
        
        # Find generated code from p04a
        code_dir = project_dir / "p04a_backend_codegen"
        
        ci_failure = context.get("ci_failure") or context.get("test_failures")
        
        if ci_failure:
            # MODE 1: Real CI repair
            return await self._run_repair(ci_failure, project_dir, phase_input)
        else:
            # MODE 2: Proactive scan
            return await self._run_scan(code_dir, phase_input)

    async def _run_repair(self, ci_failure: str, project_dir: Path, phase_input: Any) -> dict:
        """Run DCSP repair loop."""
        from aether_os.phases.p08_cicd.pipeline import run_repair
        
        # We need the generated code in a temp dir or just use the code_dir
        code_dir = project_dir / "p04a_backend_codegen" / "src"
        if not code_dir.exists():
             code_dir = project_dir / "p04a_backend_codegen"

        repair_result = run_repair(
            log_content=str(ci_failure),
            root_dir=code_dir,
            historical_records=[],
            ast_index=None,
        )

        output_dir = Path(phase_input.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        patch_path = ""
        if repair_result.success and repair_result.patch_diff:
            patch_file = output_dir / "cicd_patch.diff"
            patch_file.write_text(repair_result.patch_diff)
            patch_path = str(patch_file)

        return {
            "output_path": str(output_dir),
            "status": "repaired" if repair_result.success else "failed",
            "patch_path": patch_path,
            "explanation": repair_result.explanation,
            "confidence": repair_result.confidence
        }

    async def _run_scan(self, code_dir: Path, phase_input: Any) -> dict:
        """Run security and quality scan."""
        import subprocess
        
        output_dir = Path(phase_input.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {
            "mode": "proactive_scan",
            "issues": [],
            "files_scanned": 0,
            "security_issues": 0,
            "ci_config_generated": False
        }
        
        # Run bandit if code exists
        if code_dir.exists():
            py_files = list(code_dir.rglob("*.py"))
            results["files_scanned"] = len(py_files)
            
            if py_files:
                bandit_result = subprocess.run(
                    ["python3", "-m", "bandit", "-r", str(code_dir), "-f", "json", "-q"],
                    capture_output=True, text=True)
                
                if bandit_result.stdout:
                    try:
                        bandit_data = json.loads(bandit_result.stdout)
                        issues = bandit_data.get("results", [])
                        high = [i for i in issues if i.get("issue_severity") == "HIGH"]
                        results["security_issues"] = len(high)
                        results["issues"] = [i.get("issue_text","") for i in high[:5]]
                    except Exception as _e:
                        logger.warning("Failed to parse bandit JSON output: %s", _e)
        
        # Generate GitHub Actions CI config with real project context
        project_name = phase_input.input_data.get("project_name", "app") if hasattr(phase_input, "input_data") else "app"
        safe_name = project_name.lower().replace(" ", "-")[:40]
        ci_config = f"""name: CI — {project_name}

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    name: Test & Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-timeout httpx

      - name: Run tests
        run: pytest tests/ -v --tb=short --timeout=30

      - name: Security scan
        run: |
          pip install bandit --quiet
          bandit -r src/ -ll --exit-zero

  build:
    name: Build Docker Image
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: {safe_name}:${{{{ github.sha }}}}
"""
        ci_file = output_dir / "ci.yml"
        ci_file.write_text(ci_config)
        results["ci_config_generated"] = True
        results["ci_config_path"] = str(ci_file)

        # G14 fix: generate docker-compose.yml with prometheus wired in, and
        # inject prometheus-fastapi-instrumentator into main.py if the dep is present.
        _wire_prometheus_monitoring(code_dir, output_dir, safe_name, results)

        # Write report
        report_file = output_dir / "scan_report.json"
        with open(report_file, "w") as f:
            json.dump(results, f, indent=2)

        return {
            "output_path": str(output_dir),
            "scan_results": results,
            "status": "completed"
        }

def _wire_prometheus_monitoring(code_dir: Path, output_dir: Path, safe_name: str,
                                results: dict) -> None:
    """
    G14 fix: generate a docker-compose.yml with a prometheus service and (if the
    prometheus-fastapi-instrumentator dep is present) inject instrumentation into
    src/main.py so the /metrics endpoint actually works.
    """
    try:
        # Check if prometheus-fastapi-instrumentator is in requirements.txt
        req_file = code_dir.parent / "requirements.txt" if code_dir.exists() else None
        if req_file is None or not req_file.exists():
            # Try one level up
            for candidate in [
                code_dir / "requirements.txt",
                code_dir.parent / "requirements.txt",
                code_dir.parent.parent / "requirements.txt",
            ]:
                if candidate.exists():
                    req_file = candidate
                    break

        has_instrumentator = False
        has_prometheus_client = False
        if req_file and req_file.exists():
            req_text = req_file.read_text().lower()
            has_instrumentator = "prometheus-fastapi-instrumentator" in req_text
            has_prometheus_client = "prometheus" in req_text

        # Generate docker-compose.yml with prometheus service if monitoring dep present
        if has_instrumentator or has_prometheus_client:
            dc_yml = f"""version: '3.8'
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${{DATABASE_URL:-sqlite:///./data/app.db}}
    depends_on: []

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    depends_on:
      - app

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - prometheus
"""
            (output_dir / "docker-compose.yml").write_text(dc_yml)

            # prometheus.yml scrape config pointing at the app
            prom_yml = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: '{safe_name}'
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics
"""
            (output_dir / "prometheus.yml").write_text(prom_yml)
            results["docker_compose_generated"] = True
            results["prometheus_yml_generated"] = True

        # Inject prometheus-fastapi-instrumentator into src/main.py if needed
        if has_instrumentator and code_dir.exists():
            main_py = code_dir / "main.py"
            if not main_py.exists():
                main_py = code_dir / "src" / "main.py"
            if main_py.exists():
                content = main_py.read_text()
                # Only inject if not already instrumented
                if "Instrumentator" not in content and "/metrics" not in content:
                    inject_block = (
                        "\n# Prometheus metrics (auto-injected by p08)\n"
                        "try:\n"
                        "    from prometheus_fastapi_instrumentator import Instrumentator\n"
                        "    Instrumentator().instrument(app).expose(app)\n"
                        "except ImportError:\n"
                        "    pass\n"
                    )
                    # Insert after the first `app = FastAPI(...)` line
                    if "app = FastAPI(" in content:
                        lines = content.splitlines(keepends=True)
                        new_lines = []
                        injected = False
                        for line in lines:
                            new_lines.append(line)
                            if not injected and "app = FastAPI(" in line:
                                new_lines.append(inject_block)
                                injected = True
                        main_py.write_text("".join(new_lines))
                        results["prometheus_instrumentation_injected"] = True
    except Exception as _e:
        logger.warning("[p08] prometheus wiring failed: %s", _e)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    # Ensure output_dir in phase_input matches what we expect
    agent = CICDAgent()
    result_dict = await agent.run(phase_input)
    
    return TaskResult(
        output_path=result_dict.get("output_path", ""),
        confidence=result_dict.get("confidence", 0.9),
        success=True, # We consider scan success even if issues found
        metadata=result_dict
    )
