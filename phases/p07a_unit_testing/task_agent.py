"""P07a Unit Testing — generates pytest unit tests via LLM and runs them."""
from __future__ import annotations
import asyncio
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.codegen.entities import entity_from_label as _entity_from_label
from aether_os.phases.base import TaskResult
from aether_os.phases.p07a_unit_testing.crud_repair import repair_crud
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.runner import SandboxUnavailable

from aether_os.phases.p07a_unit_testing.openapi_payload import PAYLOAD_HELPER

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


def _normalise_entities(raw: Any) -> list:
    """Entities as dicts. The architecture step sometimes lists them as bare names ("Task"), and every consumer here
    calls .get() on them: production acceptance run 9 (22 Nov 2026) failed Stage 6 with "'str' object has no attribute
    'get'" before any test ran. Labels are turned into entities by core/codegen/entities.py, shared with p04a."""
    if not isinstance(raw, list):
        return []
    return [e if isinstance(e, dict) else _entity_from_label(e.strip())
            for e in raw if isinstance(e, dict) or (isinstance(e, str) and e.strip())]


def _reject_crud_fix(fixed: str, original: str) -> str:
    """Why a model's whole-file rewrite of crud.py must not be written, or "" when it may.

    Acceptance run 13 wrote a reply cut off mid-call (`model_dump(exclude_u`): the file no longer parsed and every test
    after it failed at collection.
    """
    try:
        compile(fixed, "crud.py", "exec")
    except SyntaxError as exc:
        return f"syntax error line {exc.lineno}: {exc.msg}"
    if "all_routers" in original and "all_routers" not in fixed:
        return "drops all_routers"
    if len(fixed) < 0.5 * len(original):
        return f"lost most of the file ({len(fixed)} of {len(original)} chars)"
    return ""


def _generate_crud_tests(src_dir: Optional[Path], project_name: str, entities: list) -> str:
    """Deterministic CRUD test generator — no LLM needed.

    Generates health, list, create, a create/get/update/delete round trip, 404 for an unknown id,
    401 without a token and 422 for a malformed body, using the first entity's table name and fields
    directly. Clients follow redirects: the backend serves /api/<table> and answers /api/<table>/ with 307
    (these tests used the slash form without following, so list/create failed against a real backend).
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
        f"{PAYLOAD_HELPER}\n"
        "\n"
        "@pytest_asyncio.fixture\n"
        "async def client():\n"
        "    from database import engine, Base\n"
        "    async with engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "    from httpx import AsyncClient\n"
        "    from httpx._transports.asgi import ASGITransport\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', follow_redirects=True) as ac:\n"
        "        yield ac\n"
        "\n"
        "\n"
        "@pytest_asyncio.fixture\n"
        "async def auth_client(client):\n"
        "    await client.post('/api/auth/register', json={'email': 'test@example.com', 'password': 'TestPass123!', 'name': 'Test User'})\n"
        "    # The app's role model is deny-by-default and sign-up creates a plain user: promote the test account\n"
        "    # to admin (admin may do everything) so the tests exercise the endpoints, not the role guard.\n"
        "    from database import AsyncSessionLocal\n"
        "    from sqlalchemy import text\n"
        "    async with AsyncSessionLocal() as db:\n"
        "        await db.execute(text(\"UPDATE users SET role = 'admin' WHERE email = 'test@example.com'\"))\n"
        "        await db.commit()\n"
        "    r = await client.post('/api/auth/login', json={'email': 'test@example.com', 'password': 'TestPass123!'})\n"
        "    token = r.json().get('access_token', '')\n"
        "    from httpx import AsyncClient\n"
        "    from httpx._transports.asgi import ASGITransport\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', follow_redirects=True, headers={'Authorization': f'Bearer {token}'}) as ac:\n"
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
        f"    response = await auth_client.get('/api/{table}')\n"
        "    assert response.status_code == 200\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_create(auth_client):\n"
        f"    body = await _payload(auth_client, '/api/{table}', {payload})\n"
        f"    response = await auth_client.post('/api/{table}', json=body)\n"
        "    assert response.status_code in (200, 201), f'Create failed: {response.status_code} {response.text[:200]}'\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_create_get_update_delete_roundtrip(auth_client):\n"
        f"    body = await _payload(auth_client, '/api/{table}', {payload})\n"
        f"    created = await auth_client.post('/api/{table}', json=body)\n"
        "    assert created.status_code in (200, 201), created.text[:200]\n"
        "    new_id = created.json().get('id')\n"
        "    assert new_id is not None\n"
        f"    got = await auth_client.get(f'/api/{table}/{{new_id}}')\n"
        "    assert got.status_code == 200\n"
        f"    updated = await auth_client.put(f'/api/{table}/{{new_id}}', json=body)\n"
        "    assert updated.status_code == 200, updated.text[:200]\n"
        f"    deleted = await auth_client.delete(f'/api/{table}/{{new_id}}')\n"
        "    assert deleted.status_code in (200, 204), deleted.text[:200]\n"
        f"    assert (await auth_client.get(f'/api/{table}/{{new_id}}')).status_code == 404\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_unknown_id_is_404(auth_client):\n"
        f"    response = await auth_client.get('/api/{table}/999999999')\n"
        "    assert response.status_code == 404\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_requires_authentication(client):\n"
        f"    response = await client.get('/api/{table}')\n"
        "    assert response.status_code in (401, 403)\n"
        "\n"
        "\n"
        "@pytest.mark.asyncio\n"
        f"async def test_rejects_an_invalid_body(auth_client):\n"
        f"    response = await auth_client.post('/api/{table}', json=['not', 'an', 'object'])\n"
        "    assert response.status_code == 422\n"
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
        import logging
        import sys
        import os

        logger = logging.getLogger(__name__)

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
            except Exception as e:
                logger.warning("p07a: table creation failed (non-critical, may already exist): %s", e)
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


async def _import_ok(cmd: list, parent: Path, env_patch: dict) -> bool:
    done = await phase_exec.run(cmd, cwd=parent, env=env_patch, timeout=20, text=True)
    return "IMPORT_OK" in done.stdout or done.returncode == 0


async def _exec_validate_startup(src_dir: Path, output_dir: Path) -> dict:
    """Try to import the generated app to catch import/syntax errors at runtime.

    Returns dict with keys: passed (bool), error (str|None), fixed (bool).
    """
    if not src_dir or not (src_dir / "main.py").exists():
        return {"passed": True, "error": None, "fixed": False}

    parent = src_dir.parent  # backend root (has src/ as package)
    env_patch = {"DATABASE_URL": "sqlite+aiosqlite:///./test_exec_validate.db", "SECRET_KEY": "test-secret"}

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

    try:
        done = await phase_exec.run(cmd, cwd=parent, env=env_patch, timeout=20, text=True)
    except asyncio.TimeoutError:
        logger.warning("[p07a] exec validation: app startup timed out after 20s — treating as failure")
        return {"passed": False, "error": "App startup timed out after 20 seconds", "fixed": False}

    out, err = done.stdout, done.stderr

    if "IMPORT_OK" in out or done.returncode == 0:
        logger.info("[p07a] exec validation: import OK")
        return {"passed": True, "error": None, "fixed": False}

    error_text = err[:1200] if err else f"return code {done.returncode}"
    logger.warning("[p07a] exec validation failed: %s", error_text[:200])

    # Attempt LLM-based repair of crud.py if the error is there (small verified patches, KAN-212)
    crud_path = src_dir / "routers" / "crud.py"
    if crud_path.exists() and ("crud" in err.lower() or "import" in err.lower()):
        try:
            if await repair_crud(src_dir, error_text) and await _import_ok(cmd, parent, env_patch):
                logger.info("[p07a] exec validation: FIXED by LLM patches")
                return {"passed": True, "error": None, "fixed": True}
        except asyncio.TimeoutError:
            logger.warning("[p07a] exec validation: re-validation after LLM fix timed out")
            return {"passed": False, "error": "App startup timed out after LLM fix (20s)", "fixed": False}
        except SandboxUnavailable:
            raise
        except Exception as _fix_exc:
            logger.warning("[p07a] LLM fix attempt failed: %s", _fix_exc)

    return {"passed": False, "error": error_text, "fixed": False}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    entities: list = _normalise_entities(data.get("entities", []))

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
        _test_env = {
            "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
            "SECRET_KEY": "test-secret-key-not-for-production",
            "PYTHONPATH": str(run_dir),
        }
        done = await phase_exec.run(
            ["python3", "-m", "pytest", str(test_file), "-v", "--tb=short",
             "-p", "no:cacheprovider", "--timeout=30"],
            cwd=run_dir, project=output_dir, env=_test_env, timeout=60, text=True)
        output_text = done.stdout + done.stderr
        (output_dir / "pytest_output.txt").write_text(output_text)

        if "passed" in output_text:
            m = re.search(r"(\d+) passed", output_text)
            test_results["passed"] = int(m.group(1)) if m else 1
        if "failed" in output_text:
            m = re.search(r"(\d+) failed", output_text)
            test_results["failed"] = int(m.group(1)) if m else 0
        if done.returncode not in (0, 1):
            test_results["errors"].append(output_text[-500:])
        logger.info("[p07a] pytest done: %s passed, %s failed", test_results["passed"], test_results["failed"])
    except asyncio.TimeoutError:
        test_results["errors"].append("pytest timed out after 60s")
        logger.warning("[p07a] pytest timed out")
    except SandboxUnavailable:
        raise  # generated tests were NOT run (never on the host): the phase fails with this message
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
    except SandboxUnavailable:
        raise
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
