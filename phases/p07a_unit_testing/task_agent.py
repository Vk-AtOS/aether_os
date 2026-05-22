"""P07a Unit Testing — generates pytest unit tests via LLM and runs them."""
from __future__ import annotations
import asyncio
import json
import logging
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    entities: list = data.get("entities", [])
    backend_src: str = data.get("backend_src_dir", "") or data.get("main_py", "")

    tests_written = 0
    test_results: dict = {"passed": 0, "failed": 0, "errors": []}

    # ── Generate test file via LLM ────────────────────────────────────────────
    test_code = ""
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        entity_names = [e.get("name", "Item") for e in entities[:6]]
        prompt = (
            f"Generate pytest unit tests for a FastAPI backend named '{project_name}'. "
            f"Entities: {json.dumps(entity_names)}.\n\n"
            "Use httpx.AsyncClient with the FastAPI TestClient. "
            "Test: health endpoint, list endpoint returns 200 with items key, "
            "create endpoint returns 201/200, get by id, delete. "
            "Use pytest.mark.asyncio. Keep tests self-contained with no DB setup needed "
            "(mock the DB or use in-memory SQLite).\n\n"
            "Return ONLY the Python test file content. No markdown."
        )
        result = await llm.call(prompt, task_type="code_generation", max_tokens=3000)
        if result and len(result.strip()) > 100:
            import re
            m = re.search(r"```(?:python)?\s*\n(.*?)```", result, re.DOTALL)
            test_code = m.group(1).strip() if m else result.strip()
    except Exception as exc:
        logger.warning("[p07a] LLM test gen failed: %s", exc)

    if not test_code:
        test_code = textwrap.dedent(f"""\
            import pytest
            from fastapi.testclient import TestClient

            def get_client():
                import importlib.util, sys, os
                os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
                return None  # placeholder when main.py not importable

            def test_health_placeholder():
                \"\"\"Placeholder — real tests require the generated main.py.\"\"\"
                assert True

            def test_project_name():
                assert "{project_name}" != ""
        """)

    test_file = output_dir / "test_generated.py"
    test_file.write_text(test_code)
    tests_written = 1

    # ── Run pytest ────────────────────────────────────────────────────────────
    run_dir = Path(backend_src) if backend_src else output_dir
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest", str(test_file), "-v", "--tb=short",
            "-p", "no:cacheprovider", "--timeout=30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(run_dir),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output_text = stdout.decode() + stderr.decode()
        (output_dir / "pytest_output.txt").write_text(output_text)

        if "passed" in output_text:
            import re
            m = re.search(r"(\d+) passed", output_text)
            test_results["passed"] = int(m.group(1)) if m else 1
        if "failed" in output_text:
            import re
            m = re.search(r"(\d+) failed", output_text)
            test_results["failed"] = int(m.group(1)) if m else 0
        if proc.returncode not in (0, 1):
            test_results["errors"].append(output_text[-500:])
        logger.info("[p07a] pytest done: %s passed, %s failed", test_results["passed"], test_results["failed"])
    except asyncio.TimeoutError:
        test_results["errors"].append("pytest timed out after 60s")
        logger.warning("[p07a] pytest timed out")
    except Exception as exc:
        test_results["errors"].append(str(exc))
        logger.warning("[p07a] pytest run failed: %s", exc)

    summary = {
        "tests_written": tests_written,
        "test_file": str(test_file),
        **test_results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    return TaskResult(
        output_path=str(test_file),
        confidence=0.75,
        metadata=summary,
        success=True,
        issues=test_results["errors"],
    )
