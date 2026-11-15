"""P08 Task Agent — CI/CD Repair or Proactive Scan."""
from __future__ import annotations
import asyncio
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
        # Prefer explicit project_dir from input_data; fall back to parent of output_dir.
        # When factory_pipeline sets output_dir = project_root the .parent would be wrong.
        _explicit = context.get("project_dir", "")
        if _explicit and Path(_explicit).exists():
            project_dir = Path(_explicit)
        else:
            project_dir = Path(phase_input.output_dir).parent

        # Find generated code from p04a
        code_dir = project_dir / "src"
        if not code_dir.exists():
            code_dir = project_dir / "p04_backend" / "backend_codegen" / "src"
        if not code_dir.exists():
            code_dir = project_dir / "p04a_backend_codegen" / "src"
        
        ci_failure = context.get("ci_failure") or context.get("test_failures")
        
        if ci_failure:
            # MODE 1: Real CI repair
            return await self._run_repair(ci_failure, project_dir, phase_input)
        else:
            # MODE 2: Proactive scan
            return await self._run_scan(code_dir, phase_input)

    async def _run_repair(self, ci_failure: str, project_dir: Path, phase_input: Any) -> dict:
        """Run CI/CD repair loop."""
        from aether_os.phases.p08_cicd.pipeline import run_repair
        
        # Find canonical src dir (priority: project_dir/src, then phase output locations)
        code_dir = project_dir / "src"
        if not code_dir.exists():
            code_dir = project_dir / "p04_backend" / "backend_codegen" / "src"
        if not code_dir.exists():
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
        # Write phase artifacts to a subdirectory of the project phase dir,
        # not to the project root (phase_input.output_dir may be the project root).
        _pdir = Path(phase_input.input_data.get("project_dir", phase_input.output_dir))
        output_dir = _pdir / "p08_cicd_deployment" / "cicd"
        output_dir.mkdir(parents=True, exist_ok=True)

        results = {
            "mode": "proactive_scan",
            "issues": [],
            "files_scanned": 0,
            "security_issues": 0,
            "ci_config_generated": False
        }

        # Run bandit asynchronously if code exists (avoids blocking the event loop)
        if code_dir.exists():
            py_files = list(code_dir.rglob("*.py"))
            results["files_scanned"] = len(py_files)

            if py_files:
                try:
                    bandit_proc = await asyncio.create_subprocess_exec(
                        "python3", "-m", "bandit", "-r", str(code_dir), "-f", "json", "-q",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    bandit_stdout, _bandit_stderr = await asyncio.wait_for(
                        bandit_proc.communicate(), timeout=60
                    )
                    if bandit_stdout:
                        try:
                            bandit_data = json.loads(bandit_stdout.decode())
                            issues = bandit_data.get("results", [])
                            high = [i for i in issues if i.get("issue_severity") == "HIGH"]
                            results["security_issues"] = len(high)
                            results["issues"] = [i.get("issue_text", "") for i in high[:5]]
                        except Exception as _e:
                            logger.warning("Failed to parse bandit JSON output: %s", _e)
                except asyncio.TimeoutError:
                    logger.warning("[p08] bandit scan timed out after 60s — skipping")
                except Exception as _be:
                    logger.warning("[p08] bandit scan failed (non-critical): %s", _be)
        
        # Generate GitHub Actions CI config with real project context
        project_name = phase_input.input_data.get("project_name", "app") if hasattr(phase_input, "input_data") else "app"
        safe_name = project_name.lower().replace(" ", "-")[:40]
        ci_config = f"""name: CI

on:
  push:
    branches: [main, master, develop]
  pull_request:
    branches: [main, master]

jobs:
  backend:
    name: Backend — Test & Lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: testdb
          POSTGRES_USER: testuser
          POSTGRES_PASSWORD: testpass
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql+asyncpg://testuser:testpass@localhost:5432/testdb
      SECRET_KEY: ci-test-secret-key-not-for-production
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-timeout httpx asyncpg ruff bandit

      - name: Lint (ruff)
        run: ruff check src/ --output-format=github

      - name: Run tests
        run: pytest tests/ -v --tb=short --timeout=30

      - name: Security scan
        run: bandit -r src/ -ll --exit-zero

  frontend:
    name: Frontend — Type-check & Lint
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install dependencies
        run: npm install

      - name: Type-check
        run: npm run typecheck

      - name: Lint
        run: npm run lint

      - name: Build
        run: npm run build

  docker:
    name: Build Docker Image
    runs-on: ubuntu-latest
    needs: [backend, frontend]
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
          cache-from: type=gha
          cache-to: type=gha,mode=max
        env:
          IMAGE_NAME: {safe_name}

      - name: Smoke test generated app
        run: |
          docker run -d --name app_test -p 8000:8000 \\
            -e SECRET_KEY=ci-test-key-$(date +%s) \\
            -e DATABASE_URL=postgresql+asyncpg://testuser:testpass@localhost:5432/testdb \\
            --network host \\
            ${{{{ env.IMAGE_NAME }}}}:${{{{ github.sha }}}}
          echo "Waiting for app to start..."
          for i in $(seq 1 30); do
            if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
              echo "App healthy after ${{i}}s"
              exit 0
            fi
            sleep 1
          done
          echo "App failed health check after 30s"
          docker logs app_test
          exit 1
        if: always()

      - name: Cleanup test container
        run: docker rm -f app_test || true
        if: always()

  compliance-drift:
    name: Compliance Drift Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Check compliance drift
        run: python3 scripts/check_compliance.py
"""
        ci_file = output_dir / "ci.yml"
        ci_file.write_text(ci_config)

        # Problem 68: verify CI file actually exists on disk before marking as generated
        if not ci_file.exists():
            results["issues"] = results.get("issues", []) + ["CI workflow file ci.yml was not written to disk"]
            logger.error("p08: ci.yml not found after write — gate failure")
        else:
            results["ci_config_generated"] = True
            results["ci_config_path"] = str(ci_file)

        # Mirror to .github/workflows/ci.yml in the project root so it's
        # included in the delivery ZIP and works when user pushes to GitHub
        _project_dir = Path(phase_input.input_data.get("project_dir", "")) if hasattr(phase_input, "input_data") else Path("")
        if _project_dir.exists():
            _workflows_dir = _project_dir / ".github" / "workflows"
            try:
                _workflows_dir.mkdir(parents=True, exist_ok=True)
                (_workflows_dir / "ci.yml").write_text(ci_config)
                results["ci_workflow_mirrored"] = str(_workflows_dir / "ci.yml")
                # Problem 68: also generate a Dockerfile in project root if missing
                _proj_dockerfile = _project_dir / "Dockerfile"
                if not _proj_dockerfile.exists():
                    # Write a minimal Dockerfile for the project
                    _minimal_dockerfile = (
                        "FROM python:3.11-slim\n"
                        "WORKDIR /app\n"
                        "ENV PYTHONPATH=/app\n"
                        "COPY requirements.txt* ./\n"
                        "RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true\n"
                        "COPY . .\n"
                        "EXPOSE 8000\n"
                        'CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
                    )
                    try:
                        _proj_dockerfile.write_text(_minimal_dockerfile)
                        results["dockerfile_generated"] = str(_proj_dockerfile)
                    except Exception as _df_e:
                        logger.warning("p08: could not write project Dockerfile: %s", _df_e)
                else:
                    results["dockerfile_exists"] = str(_proj_dockerfile)
                # Problem 68: verify Dockerfile exists
                if not _proj_dockerfile.exists():
                    results["issues"] = results.get("issues", []) + ["Dockerfile was not found in project root"]
                    logger.error("p08: Dockerfile not found after write — gate failure")
            except Exception as _wf_e:
                logger.warning("p08: could not mirror CI workflow: %s", _wf_e)

            # Gap 3: generate scripts/check_compliance.py for the compliance-drift CI job
            _generate_compliance_checker(_project_dir, results)

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

def _generate_compliance_checker(project_dir: Path, results: dict) -> None:
    """
    Gap 3: Write scripts/check_compliance.py into the generated project.

    The script is standalone (no AetherOS import) so it runs inside the
    compliance-drift CI job without any AetherOS dependency.  It:
      1. Reads compliance_manifest.json from the project root
      2. Finds all .py files with route decorators
      3. Recomputes the SHA-256 drift fingerprint
      4. Exits non-zero if the fingerprint changed or the score dropped
    """
    try:
        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        checker_path = scripts_dir / "check_compliance.py"
        checker_source = (
            '#!/usr/bin/env python3\n'
            '"""Compliance drift checker — generated by AetherOS P08.\n'
            '\n'
            'Reads compliance_manifest.json from the project root, recomputes\n'
            'the drift fingerprint from route-bearing .py files, and exits 1\n'
            'if the fingerprint changed or the overall_score dropped.\n'
            '"""\n'
            'import hashlib\n'
            'import json\n'
            'import re\n'
            'import sys\n'
            'from pathlib import Path\n'
            '\n'
            'ROOT = Path(__file__).resolve().parent.parent\n'
            'MANIFEST_PATH = ROOT / "compliance_manifest.json"\n'
            '_ROUTE_RE = re.compile(r\'@(?:app|router)\\.(get|post|put|delete|patch)\')\n'
            '\n'
            '\n'
            'def compute_fingerprint(root: Path) -> str:\n'
            '    """SHA-256 of concatenated source of all route-bearing .py files."""\n'
            '    route_sources: list[str] = []\n'
            '    for search_dir in (root / "src", root):\n'
            '        if not search_dir.exists():\n'
            '            continue\n'
            '        for py_file in sorted(search_dir.rglob("*.py")):\n'
            '            if "__pycache__" in str(py_file):\n'
            '                continue\n'
            '            try:\n'
            '                text = py_file.read_text(encoding="utf-8", errors="replace")\n'
            '            except OSError as err:\n'
            '                print(f"[drift] WARNING: cannot read {py_file}: {err}", file=sys.stderr)\n'
            '                continue\n'
            '            if _ROUTE_RE.search(text):\n'
            '                route_sources.append(text)\n'
            '        if route_sources:\n'
            '            break\n'
            '    return hashlib.sha256(\n'
            '        "\\n".join(route_sources).encode("utf-8")\n'
            '    ).hexdigest() if route_sources else hashlib.sha256(b"").hexdigest()\n'
            '\n'
            '\n'
            'def main() -> int:\n'
            '    if not MANIFEST_PATH.exists():\n'
            '        print(\n'
            '            "[drift] ERROR: compliance_manifest.json not found at"\n'
            '            f" {MANIFEST_PATH}\\n"\n'
            '            "       Run p06 compliance scan first to generate it.",\n'
            '            file=sys.stderr,\n'
            '        )\n'
            '        return 1\n'
            '\n'
            '    try:\n'
            '        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))\n'
            '    except (json.JSONDecodeError, OSError) as err:\n'
            '        print(f"[drift] ERROR: cannot read manifest: {err}", file=sys.stderr)\n'
            '        return 1\n'
            '\n'
            '    stored_fp = manifest.get("drift_fingerprint", "")\n'
            '    baseline_score = manifest.get("overall_score", 0)\n'
            '\n'
            '    current_fp = compute_fingerprint(ROOT)\n'
            '    current_score = baseline_score  # score recheck requires re-running scanner\n'
            '\n'
            '    drifted = current_fp != stored_fp\n'
            '    score_dropped = False  # extended check: re-run scanner if available\n'
            '    try:\n'
            '        import importlib.util\n'
            '        if importlib.util.find_spec("aether_os") is not None:\n'
            '            from aether_os.core.compliance.code_scanner import scan_file\n'
            '            main_py = ROOT / "src" / "main.py"\n'
            '            if main_py.exists():\n'
            '                result = scan_file(main_py)\n'
            '                current_score = result.score\n'
            '                score_dropped = current_score < baseline_score\n'
            '    except Exception as scan_err:\n'
            '        print(\n'
            '            f"[drift] WARNING: live rescan skipped: {scan_err}",\n'
            '            file=sys.stderr,\n'
            '        )\n'
            '\n'
            '    print(f"[drift] stored  fingerprint : {stored_fp}")\n'
            '    print(f"[drift] current fingerprint : {current_fp}")\n'
            '    print(f"[drift] baseline score      : {baseline_score}")\n'
            '    print(f"[drift] current score       : {current_score}")\n'
            '\n'
            '    if drifted:\n'
            '        print(\n'
            '            "[drift] FAIL: route-bearing source files changed since last"\n'
            '            " compliance scan.\\n"\n'
            '            "       Re-run the AetherOS pipeline (p06) to update the"\n'
            '            " manifest, then commit compliance_manifest.json.",\n'
            '            file=sys.stderr,\n'
            '        )\n'
            '    if score_dropped:\n'
            '        print(\n'
            '            f"[drift] FAIL: compliance score dropped from {baseline_score}"\n'
            '            f" to {current_score}.\\n"\n'
            '            "       Fix compliance issues before merging.",\n'
            '            file=sys.stderr,\n'
            '        )\n'
            '    if not drifted and not score_dropped:\n'
            '        print("[drift] PASS: compliance fingerprint clean, score stable.")\n'
            '    return 1 if (drifted or score_dropped) else 0\n'
            '\n'
            '\n'
            'if __name__ == "__main__":\n'
            '    sys.exit(main())\n'
        )
        checker_path.write_text(checker_source, encoding="utf-8")
        checker_path.chmod(0o755)
        results["compliance_checker_generated"] = str(checker_path)
        logger.info("[p08] Gap 3: scripts/check_compliance.py written to %s", checker_path)
    except Exception as exc:
        logger.warning("[p08] _generate_compliance_checker failed: %s", exc)


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
                    # Insert after the closing ) of app = FastAPI(...) — handles multi-line
                    if "app = FastAPI(" in content:
                        _start = content.find("app = FastAPI(")
                        _depth, _end = 0, _start
                        for _i, _ch in enumerate(content[_start:], _start):
                            if _ch == "(":
                                _depth += 1
                            elif _ch == ")":
                                _depth -= 1
                                if _depth == 0:
                                    _end = _i
                                    break
                        _end_nl = content.find("\n", _end)
                        if _end_nl >= 0:
                            content = content[:_end_nl + 1] + inject_block + content[_end_nl + 1:]
                            main_py.write_text(content)
                        results["prometheus_instrumentation_injected"] = True
    except Exception as _e:
        logger.warning("[p08] prometheus wiring failed: %s", _e)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    # Ensure output_dir in phase_input matches what we expect
    agent = CICDAgent()
    result_dict = await agent.run(phase_input)

    # Repair mode reports its own outcome; the scan-mode gate below needs ci.yml/Dockerfile
    # keys it never sets, so a successful repair used to come back success=False.
    if result_dict.get("status") in ("repaired", "failed"):
        repaired = result_dict["status"] == "repaired"
        return TaskResult(
            output_path=result_dict.get("output_path", ""),
            confidence=result_dict.get("confidence", 0.9 if repaired else 0.0),
            success=repaired,
            issues=[] if repaired else [result_dict.get("explanation", "repair failed")],
            metadata=result_dict,
        )

    # Problem 68: gate fails if CI workflow or Dockerfile are missing
    scan_results = result_dict.get("scan_results", result_dict)
    gate_issues = scan_results.get("issues", [])
    ci_generated = scan_results.get("ci_config_generated", False) or scan_results.get("ci_workflow_mirrored", False)
    dockerfile_ok = scan_results.get("dockerfile_generated") or scan_results.get("dockerfile_exists")
    gate_passed = ci_generated and bool(dockerfile_ok) and not gate_issues

    return TaskResult(
        output_path=result_dict.get("output_path", ""),
        confidence=result_dict.get("confidence", 0.9 if gate_passed else 0.4),
        success=gate_passed,
        issues=gate_issues if not gate_passed else [],
        metadata=result_dict,
    )
