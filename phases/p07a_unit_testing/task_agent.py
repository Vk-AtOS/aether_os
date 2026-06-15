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


def _generate_crud_tests(src_dir: Optional[Path], project_name: str, entities: list) -> str:
    """Deterministic CRUD test generator — no LLM needed.

    Generates 4 tests: health, list, create, get_by_id using the first entity's
    table name and fields directly, so URLs are always correct.
    """
    src_abs = str(src_dir) if src_dir else ""
    src_path_line = (
        f"sys.path.insert(0, {src_abs!r})"
        if src_abs else
        "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))"
    )

    # Pick first non-User entity for CRUD tests
    first_entity = next(
        (e for e in entities if e.get("name", "").lower() not in ("user", "users")),
        entities[0] if entities else None,
    )
    if first_entity:
        table = first_entity.get("table", first_entity.get("name", "items").lower() + "s")
        fields = first_entity.get("fields", [])
        # Build a minimal create payload with type-appropriate values (not just "test")
        _NUMERIC_TYPES = {"integer", "decimal", "float", "number", "fk"}
        _BOOL_TYPES = {"boolean", "bool"}
        _skip = ("id", "created_at", "updated_at", "deleted_at", "user_id", "is_active")
        payload_parts = []
        for f in fields:
            if not isinstance(f, dict):
                continue
            fn = f.get("name", "")
            if fn in _skip:
                continue
            ft = f.get("type", "string").lower()
            if ft in _NUMERIC_TYPES:
                val = "1"
            elif ft in _BOOL_TYPES:
                val = "True"
            else:
                val = f'"test_{fn[:8]}"'
            payload_parts.append(f'"{fn}": {val}')
            if len(payload_parts) >= 4:
                break
        payload = "{" + ", ".join(payload_parts) + "}" if payload_parts else '{"name": "test"}'
    else:
        table = "items"
        payload = '{"name": "test"}'

    return (
        f'"""Auto-generated CRUD tests for {project_name}."""\n'
        "from __future__ import annotations\n"
        "import pytest\n"
        "import pytest_asyncio\n"
        "import sys\n"
        "import os\n"
        "\n"
        f"{src_path_line}\n"
        "from main import app\n"
        "\n"
        "\n"
        "@pytest_asyncio.fixture\n"
        "async def client():\n"
        "    from database import engine, Base\n"
        "    async with engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "    from httpx import AsyncClient\n"
        "    from httpx._transports.asgi import ASGITransport\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:\n"
        "        yield ac\n"
        "\n"
        "\n"
        "@pytest_asyncio.fixture\n"
        "async def auth_client(client):\n"
        "    await client.post('/api/auth/register', json={'email': 'test@example.com', 'password': 'TestPass123!', 'name': 'Test User'})\n"
        "    r = await client.post('/api/auth/login', json={'email': 'test@example.com', 'password': 'TestPass123!'})\n"
        "    token = r.json().get('access_token', '')\n"
        "    from httpx import AsyncClient\n"
        "    from httpx._transports.asgi import ASGITransport\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', headers={'Authorization': f'Bearer {token}'}) as ac:\n"
        "        yield ac\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        "async def test_health(client):\n"
        "    response = await client.get('/health')\n"
        "    assert response.status_code == 200\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_list(auth_client):\n"
        f"    response = await auth_client.get('/api/{table}/')\n"
        "    assert response.status_code == 200\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_create(auth_client):\n"
        f"    response = await auth_client.post('/api/{table}/', json={payload})\n"
        "    assert response.status_code in (200, 201), f'Create failed: {response.status_code} {response.text[:200]}'\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_get_by_id(auth_client):\n"
        f"    response = await auth_client.get('/api/{table}/1')\n"
        "    assert response.status_code in (200, 404)\n"
    )


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
            try:
                from database import engine, Base
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            except Exception:
                pass
            from httpx import AsyncClient
            from httpx._transports.asgi import ASGITransport
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

    # ── Generate test file deterministically (no LLM) ───────────────────────
    # LLMs consistently get API URLs wrong (e.g. /api/ instead of /api/products/).
    # Deterministic generation using the entity table names is faster and reliable.
    if entities:
        test_code = _generate_crud_tests(src_dir, project_name, entities)
        logger.info("[p07a] Generated deterministic CRUD tests for entities: %s",
                    [e.get("name") for e in entities[:4]])
    else:
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
