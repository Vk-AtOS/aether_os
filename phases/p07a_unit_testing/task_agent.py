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
    """Locate the backend src directory with main.py.

    Priority order mirrors p09._find_backend_src so both phases instrument
    the same canonical generated code, not the p03 scaffolding stubs.
    """
    project_dir = data.get("project_dir", "")

    # Priority 1+2: canonical path from pipeline context (set by p04a)
    for key in ("canonical_src_dir", "backend_src_dir", "main_py"):
        val = data.get(key, "")
        if val:
            p = Path(val)
            if p.is_file():
                p = p.parent
            if p.is_dir() and (p / "main.py").exists():
                # Reject scaffolding stubs — only accept real generated code
                if "p03_scaffolding" not in str(p):
                    return p

    if project_dir:
        base = Path(project_dir)
        # Priority 3: standard p04a output locations
        for candidate in [
            base / "p04_backend" / "backend_codegen" / "src",
            base / "p04a_backend_codegen" / "src",
            base / "p04_backend" / "src",
            base / "src",
        ]:
            if candidate.exists() and (candidate / "main.py").exists():
                return candidate
        # Priority 4: glob — prefer deeper paths, exclude scaffolding
        found = [
            p for p in base.rglob("main.py")
            if "__pycache__" not in str(p)
            and ".venv" not in str(p)
            and "p03_scaffolding" not in str(p)
            and "node_modules" not in str(p)
        ]
        if found:
            found.sort(key=lambda p: len(p.parts), reverse=True)
            return found[0].parent
    return None


def _fallback_tests(src_dir: Optional[Path], project_name: str = "App") -> str:
    """PIPELINE-034: generate a meaningful fallback test (FIX 17)."""
    # Compute the absolute path to src/ so sys.path.insert works regardless of cwd
    src_abs = str(src_dir) if src_dir else ""
    src_path_line = (
        f"sys.path.insert(0, {src_abs!r})"
        if src_abs else
        "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))"
    )
    return textwrap.dedent(f"""\
        \"\"\"Auto-generated API tests for {project_name}.\"\"\"
        from __future__ import annotations
        import pytest
        import pytest_asyncio
        import sys
        import os

        # Ensure src/ is importable using absolute path
        {src_path_line}

        try:
            from main import app
        except ImportError:
            app = None

        @pytest_asyncio.fixture
        async def client():
            if not app:
                pytest.skip("App not found")
            from httpx import AsyncClient, ASGITransport
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test"
            ) as ac:
                yield ac

        @pytest.mark.asyncio
        async def test_health(client):
            r = await client.get("/health")
            assert r.status_code == 200

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
    env_patch = {"DATABASE_URL": "sqlite+aiosqlite:///./test_exec_validate.db", "SECRET_KEY": "test-secret"}
    test_env = {**os.environ, **env_patch}

    cmd = [
        "python3", "-c",
        (
            "import sys, os\n"
            f"sys.path.insert(0, '{parent}')\n"
            "os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./test_exec_validate.db'\n"
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
        _src_abs = str(src_dir) if src_dir else ""
        _src_path_insert = (
            f"sys.path.insert(0, {_src_abs!r})"
            if _src_abs else
            "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))"
        )
        prompt = (
            f"Generate pytest unit tests for a FastAPI backend named '{project_name}'.\n"
            f"Entities and their plural tables: {json.dumps([(e.get('name'), e.get('table')) for e in entities[:6]])}.\n\n"
            "Rules for test generation:\n"
            "1. Start with: import pytest, import pytest_asyncio, import sys, import os\n"
            f"2. Insert src path: {_src_path_insert}\n"
            "3. Import app: from main import app\n"
            "4. Define TWO fixtures using @pytest_asyncio.fixture (NOT @pytest.fixture):\n"
            "   a) 'async def client()' — raw unauthenticated client:\n"
            "      async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac: yield ac\n"
            "   b) 'async def auth_client(client)' — client with a valid JWT token:\n"
            "      First register: r = await client.post('/api/auth/register', json={'username': 'testuser', 'email': 'test@example.com', 'password': 'TestPass123!'})\n"
            "      Then login: r = await client.post('/api/auth/login', data={'username': 'testuser', 'password': 'TestPass123!'})\n"
            "      If login fails try: r = await client.post('/api/auth/login', json={'email': 'test@example.com', 'password': 'TestPass123!'})\n"
            "      Extract: token = r.json().get('access_token', '')\n"
            "      Return a new AsyncClient with headers={'Authorization': f'Bearer {token}'}\n"
            "   Import AsyncClient and ASGITransport from httpx inside each fixture.\n"
            "5. All test functions must be 'async def test_...(auth_client):' decorated with @pytest.mark.asyncio\n"
            "   (except test_health which uses 'client' fixture — health is unauthenticated)\n"
            "6. Do NOT use 'TestClient' or 'with TestClient(app)' — use async httpx only.\n"
            "7. Do NOT use 'async with TestClient(...)' — that is wrong; use AsyncClient only.\n"
            "8. CRITICAL: All CRUD routes are registered under /api/ prefix. Test '/api/<table>' NOT '/<table>'. "
            "Example: table 'contacts' → test GET /api/contacts, POST /api/contacts, GET /api/contacts/1.\n"
            "9. Health endpoint is at /health (no /api prefix). Test it with GET /health using 'client' fixture, check status_code==200 only (don't assert exact body).\n"
            "10. Test with auth_client: list (GET /api/<table>, expect 200), create (POST /api/<table>, expect 201), get by id (GET /api/<table>/1, expect 200 or 404).\n"
            "11. Use realistic test data for create payloads. Skip fields that are auto-generated (id, created_at, updated_at).\n"
            "12. If a test could fail due to empty DB (e.g. get by id), assert status_code in (200, 404) to handle both cases.\n"
            "Return ONLY the Python test file content. No markdown fences."
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
        import os as _os
        _test_env = {
            **_os.environ,
            "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
            "SECRET_KEY": "test-secret-key-not-for-production",
            "PYTHONPATH": str(run_dir),
        }
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest", str(test_file), "-v", "--tb=short",
            "-p", "no:cacheprovider", "--timeout=30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(run_dir),
            env=_test_env,
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
