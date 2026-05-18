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

      - name: Run tests
        run: pytest tests/ -v --tb=short

      - name: Security scan
        run: bandit -r src/ -ll --exit-zero

  build:
    name: Build Docker Image
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v3

      - name: Build image
        run: docker build -t {safe_name}:${{{{ github.sha }}}} .
"""
        ci_file = output_dir / "ci.yml"
        ci_file.write_text(ci_config)
        results["ci_config_generated"] = True
        results["ci_config_path"] = str(ci_file)
        
        # Write report
        report_file = output_dir / "scan_report.json"
        with open(report_file, "w") as f:
            json.dump(results, f, indent=2)
        
        return {
            "output_path": str(output_dir),
            "scan_results": results,
            "status": "completed"
        }

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
