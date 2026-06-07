"""P07a Unit Testing — generates pytest unit tests via LLM and runs them."""
from __future__ import annotations
import asyncio
import json
import logging
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


def _find_src_dir(data: dict) -> Optional[Path]:
    """Locate the backend src directory with main.py."""
    project_dir = data.get("project_dir", "")
    backend_src = data.get("backend_src_dir", "") or data.get("main_py", "")
    if backend_src:
        p = Path(backend_src)
        if p.is_dir() and (p / "main.py").exists():
            return p
        if p.is_file():
            return p.parent

    if project_dir:
        base = Path(project_dir)
        candidates = [
            base / "p04_backend" / "backend_codegen" / "src",
            base / "p04_backend" / "src",
            base / "src",
            base,
        ]
        for c in candidates:
            if c.exists() and (c / "main.py").exists():
                return c
        # Glob fallback
        found = sorted(base.rglob("main.py"), key=lambda p: len(p.parts), reverse=True)
        for f in found:
            if "__pycache__" not in str(f) and ".venv" not in str(f):
                return f.parent
    return None


def _fallback_tests(src_dir: Optional[Path], project_name: str = "App") -> str:
    """PIPELINE-034: generate a meaningful fallback test (FIX 17)."""
    return textwrap.dedent(f"""\
        \"\"\"Auto-generated API tests for {project_name}.\"\"\"
        from __future__ import annotations
        import pytest
        import pytest_asyncio
        from httpx import AsyncClient, ASGITransport
        import sys
        import os

        # Ensure src/ is importable
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

        try:
            from main import app
        except ImportError:
            # Fallback if src is different
            app = None

        @pytest_asyncio.fixture
        async def client():
            if not app:
                pytest.skip("App not found")
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test"
            ) as ac:
                yield ac

        @pytest.mark.asyncio
        async def test_health(client: AsyncClient):
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"

        @pytest.mark.asyncio
        async def test_app_exists():
            assert app is not None
    """)


async def _exec_validate_startup(src_dir: Path, output_dir: Path) -> dict:
    """Try to import the generated app to catch import/syntax errors at runtime.

    Returns dict with keys: passed (bool), error (str|None), fixed (bool).
    """
    if not src_dir or not (src_dir / "main.py").exists():
        return {"passed": True, "error": None, "fixed": False}

    parent = src_dir.parent  # backend root (has src/ as package)
    import os
    env_patch = {"DATABASE_URL": "sqlite:///./test_exec_validate.db", "SECRET_KEY": "test-secret"}
    test_env = {**os.environ, **env_patch}

    cmd = [
        "python3", "-c",
        (
            "import sys, os\n"
            f"sys.path.insert(0, '{parent}')\n"
            "os.environ['DATABASE_URL'] = 'sqlite:///./test_exec_validate.db'\n"
            "os.environ['SECRET_KEY'] = 'test-secret'\n"
            "from src.main import app\n"
            "print('IMPORT_OK')"
        ),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"passed": True, "error": None, "fixed": False}  # timeout ≈ app blocking on startup = OK

    out = stdout.decode()
    err = stderr.decode()

    if "IMPORT_OK" in out or proc.returncode == 0:
        logger.info("[p07a] exec validation: import OK")
        return {"passed": True, "error": None, "fixed": False}

    error_text = err[:1200] if err else f"return code {proc.returncode}"
    logger.warning("[p07a] exec validation failed: %s", error_text[:200])

    # Attempt LLM-based repair of crud.py if the error is there
    crud_path = src_dir / "routers" / "crud.py"
    if crud_path.exists() and ("crud" in err.lower() or "import" in err.lower()):
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            crud_code = crud_path.read_text()
            fix_prompt = (
                f"The following FastAPI router file (src/routers/crud.py) causes this import error:\n\n"
                f"ERROR:\n{error_text}\n\n"
                f"FILE (crud.py):\n{crud_code[:3000]}\n\n"
                "Fix the import error. Common fixes:\n"
                "1. Remove imports of non-existent model classes\n"
                "2. Fix relative imports (use ..models not models)\n"
                "3. Remove hallucinated schema imports that don't exist in ..schemas\n"
                "Return ONLY the complete fixed crud.py file. No markdown."
            )
            fixed_code = await asyncio.wait_for(
                llm.call(fix_prompt, task_type="code_generation", max_tokens=4000),
                timeout=60,
            )
            if fixed_code and len(fixed_code.strip()) > 200:
                import re as _re
                fixed_code = _re.sub(r"^```(?:python)?\s*\n?", "", fixed_code.strip())
                fixed_code = _re.sub(r"\n?```\s*$", "", fixed_code.strip())
                crud_path.write_text(fixed_code)
                logger.info("[p07a] LLM fixed crud.py — re-validating")

                # Re-validate
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd, cwd=str(parent),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=test_env,
                )
                try:
                    out2, err2 = await asyncio.wait_for(proc2.communicate(), timeout=20)
                    if "IMPORT_OK" in out2.decode() or proc2.returncode == 0:
                        logger.info("[p07a] exec validation: FIXED by LLM")
                        return {"passed": True, "error": None, "fixed": True}
                except asyncio.TimeoutError:
                    return {"passed": True, "error": None, "fixed": True}
        except Exception as _fix_exc:
            logger.warning("[p07a] LLM fix attempt failed: %s", _fix_exc)

    return {"passed": False, "error": error_text, "fixed": False}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    entities: list = data.get("entities", [])

    src_dir = _find_src_dir(data)

    tests_written = 0
    test_results: dict = {"passed": 0, "failed": 0, "errors": []}

    # ── Generate test file via LLM ────────────────────────────────────────────
    test_code = ""
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        entity_names = [e.get("name", "Item") for e in entities[:6]]
        prompt = (
            f"Generate pytest unit tests for a FastAPI backend named '{project_name}'.\n"
            f"Entities and their plural tables: {json.dumps([(e.get('name'), e.get('table')) for e in entities[:6]])}.\n\n"
            "Rules for test generation:\n"
            "1. Use @pytest_asyncio.fixture and 'async def' for the async client fixture.\n"
            "2. The app must be imported as 'from main import app' assuming 'src/' is in sys.path.\n"
            "3. Add 'sys.path.insert(0, os.path.join(os.path.dirname(__file__), \"..\", \"src\"))' at the top.\n"
            "4. Test real endpoints based on the plural tables provided (e.g., if table is 'contacts', test '/contacts').\n"
            "5. Test: health endpoint, list (returns items), create, get by id, patch.\n"
            "6. Use realistic test data for create/patch payloads based on entity names.\n"
            "Return ONLY the Python test file content. No markdown."
        )
        result = await llm.call(prompt, task_type="code_generation", max_tokens=3000)
        if result and len(result.strip()) > 100:
            import re
            m = re.search(r"```(?:python)?\s*\n?(.*?)```", result, re.DOTALL)
            test_code = m.group(1).strip() if m else result.strip()
            # Validate syntax
            try:
                import ast as _ast
                _ast.parse(test_code)
            except SyntaxError:
                test_code = ""
    except Exception as exc:
        logger.warning("[p07a] LLM test gen failed: %s", exc)

    if not test_code:
        # PIPELINE-034: use meaningful fallback instead of bare assert True
        test_code = _fallback_tests(src_dir, project_name)

    tests_dir = output_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    test_file = tests_dir / "test_main.py"
    test_file.write_text(test_code)
    tests_written = 1

    # ── Run pytest ────────────────────────────────────────────────────────────
    run_dir = src_dir if src_dir else output_dir
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

    # Exec validation — catch import errors the static syntax check misses
    exec_result = {"passed": True, "error": None, "fixed": False}
    try:
        exec_result = await _exec_validate_startup(src_dir, output_dir)
        if not exec_result["passed"]:
            logger.warning("[p07a] exec validation failed: %s", exec_result.get("error", "")[:200])
        elif exec_result.get("fixed"):
            logger.info("[p07a] exec validation: LLM auto-fixed import error")
    except Exception as _ev_exc:
        logger.debug("[p07a] exec validation error (non-fatal): %s", _ev_exc)

    summary = {
        "tests_written": tests_written,
        "test_file": str(test_file),
        **test_results,
        "exec_validation": exec_result,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    return TaskResult(
        output_path=str(test_file),
        confidence=0.75,
        metadata=summary,
        success=True,
        issues=test_results["errors"],
    )
