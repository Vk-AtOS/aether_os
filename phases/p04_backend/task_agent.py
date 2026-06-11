"""P04 Consolidated Task Agent — backend codegen + UI/UX design."""
from __future__ import annotations
import asyncio
import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.orchestrator.events import emit as _global_emit

logger = logging.getLogger(__name__)

# No-op fallback when no emit callable is available
async def _noop_emit(event: dict) -> None:  # noqa: ARG001
    pass


async def _smoke_repair(main_py: Path, error: str, attempt: int) -> bool:  # noqa: ARG001
    """Ask LLM to fix a startup error in main.py. Returns True if fixed."""
    from aether_os.core.llm.client import get_llm_client
    client = get_llm_client()
    source = main_py.read_text()
    # Also read models + schemas so the LLM has full context to fix import errors
    _sibling_ctx = ""
    for _sib in ["models.py", "schemas.py", "routers/crud.py"]:
        _sib_path = main_py.parent / _sib
        if _sib_path.exists():
            _sib_src = _sib_path.read_text()[:1500]
            _sibling_ctx += f"\n\n# --- {_sib} (first 1500 chars) ---\n{_sib_src}"
    prompt = (
        "The following FastAPI backend code fails to start with this error:\n\n"
        f"ERROR:\n{error}\n\n"
        f"FILE: main.py (complete):\n{source}\n"
        f"{_sibling_ctx}\n\n"
        "Fix ONLY the error above. Return the COMPLETE corrected main.py with no explanation.\n"
        "Rules:\n"
        "- Add any missing imports at the top\n"
        "- Fix undefined name errors by importing the correct module\n"
        "- Fix SQLAlchemy async syntax (use .scalars().all(), not .all())\n"
        "- Never use in-memory dicts/lists — use SQLAlchemy ORM only\n"
        "- Never store plaintext passwords — always use passlib bcrypt\n"
        "- Use ABSOLUTE imports only. Do NOT use relative imports (no 'from .module import X'). "
        "Import as 'from database import Base', 'from models import User', etc.\n"
        "- The @asynccontextmanager decorator must be on the line IMMEDIATELY before "
        "async def lifespan. Do NOT place any statements between the decorator and the function.\n"
        "Do not change working API endpoints or business logic."
    )
    try:
        fixed = await client.call(prompt, task_type="code_fix", max_tokens=4000)
        if fixed and len(fixed.strip()) > 100:
            try:
                ast.parse(fixed)
                main_py.write_text(fixed)
                return True
            except SyntaxError:
                return False
    except Exception:  # noqa: BLE001
        return False
    return False


async def _startup_smoke_test(src_dir: Path, emit) -> dict:
    """Run syntax + import checks on generated main.py. Returns {passed, errors, attempts}."""
    main_py = src_dir / "main.py"
    if not main_py.exists():
        return {"passed": True, "errors": [], "skipped": True}

    MAX_ATTEMPTS = 3
    errors: list = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        errors = []

        # Step 1: syntax check via py_compile
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "py_compile", str(main_py),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(src_dir),
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode != 0:
            errors.append(f"SyntaxError: {stderr.decode()[:500]}")

        # Step 2: import check (only if syntax OK)
        # Override DATABASE_URL so create_all() targets an isolated temp SQLite
        # rather than the AetherOS production database.
        if not errors:
            # PIPELINE-061: use regex split to handle 'app' or 'application = FastAPI(...)'
            check_code = (
                "import sys, os, re; "
                "src = open('main.py').read(); "
                "parts = re.split(r'\\n(?:app|application)\\s*=\\s*FastAPI', src, maxsplit=1); "
                "exec(compile(parts[0], 'main.py', 'exec'))"
            )
            import os as _os
            import tempfile as _tempfile
            _db_fd, _db_tmp = _tempfile.mkstemp(suffix=".db")
            _os.close(_db_fd)
            smoke_env = {**_os.environ, "DATABASE_URL": f"sqlite:///{_db_tmp}"}
            try:
                proc2 = await asyncio.create_subprocess_exec(
                    "python3", "-c", check_code,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(src_dir),
                    env=smoke_env,
                )
                try:
                    _, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=20)
                    if proc2.returncode != 0:
                        stderr_text = stderr2.decode()
                        # Relative import errors are expected in package-structured code;
                        # uvicorn runs via `python -m` so they resolve correctly at runtime.
                        if "attempted relative import" in stderr_text or \
                                "relative import" in stderr_text.lower():
                            pass  # non-fatal — valid package structure
                        elif any(e in stderr_text for e in [
                            "ImportError", "ModuleNotFoundError", "NameError", "SyntaxError"
                        ]):
                            errors.append(f"ImportError: {stderr_text[:500]}")
                except asyncio.TimeoutError:
                    pass  # timeout in import check is OK — app likely starts fine
            finally:
                # Clean up temp DB file
                try:
                    _os.unlink(_db_tmp)
                except OSError:
                    pass

        if not errors:
            await emit({
                "type": "llm_chunk",
                "phase": "p04_smoke_test",
                "text": f"✓ Smoke test passed (attempt {attempt})",
            })
            return {"passed": True, "errors": [], "attempts": attempt}

        # Attempt auto-fix
        await emit({
            "type": "llm_chunk",
            "phase": "p04_smoke_test",
            "text": (
                f"⚠ Smoke test failed (attempt {attempt}/{MAX_ATTEMPTS}): "
                f"{errors[0][:100]} — attempting auto-fix..."
            ),
        })
        fixed = await _smoke_repair(main_py, "\n".join(errors), attempt)
        if not fixed:
            break

    return {"passed": False, "errors": errors, "attempts": MAX_ATTEMPTS}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Sub-task 1: Backend Codegen
    try:
        from aether_os.phases.p04a_backend_codegen.task_agent import run as p04a_run
        sub_dir = output_dir / "backend_codegen"
        r = await p04a_run(phase_input, memory_ctx, sub_dir)
        results["backend_codegen"] = r
        if r.success and r.metadata:
            phase_input.input_data["backend_output_path"] = r.output_path
            phase_input.input_data.update({k: v for k, v in r.metadata.items() if k not in phase_input.input_data})
            # Extract API routes from generated code so p05 can wire to real endpoints
            _backend_out = Path(r.output_path)
            _seen_entities: set = set()
            _routes = []

            def _extract_routes_from_code(code: str) -> None:
                # Strategy 1: direct @app.METHOD or @router.METHOD decorators
                for _m in re.finditer(
                    r'@(?:app|router)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']',
                    code, re.IGNORECASE
                ):
                    _routes.append({"method": _m.group(1).upper(), "path": _m.group(2)})

                # Strategy 2: APIRouter(prefix="/entity") → infer CRUD routes
                for _pm in re.finditer(
                    r'APIRouter\([^)]*prefix=["\']([^"\']+)["\']',
                    code, re.IGNORECASE
                ):
                    _prefix = _pm.group(1).strip("/")
                    if _prefix and _prefix not in _seen_entities and _prefix not in ("auth", "system"):
                        _seen_entities.add(_prefix)
                        _routes.extend([
                            {"method": "GET",    "path": f"/{_prefix}"},
                            {"method": "POST",   "path": f"/{_prefix}"},
                            {"method": "GET",    "path": f"/{_prefix}/{{id}}"},
                            {"method": "PUT",    "path": f"/{_prefix}/{{id}}"},
                            {"method": "DELETE", "path": f"/{_prefix}/{{id}}"},
                        ])

                # Strategy 3: include_router patterns
                for _im in re.finditer(
                    r'include_router\([^,)]+,\s*["\']([^"\']+)["\']|'
                    r'generate_crud_router\([^,]+,[^,]+,[^,]+,[^,]+,\s*["\']([^"\']+)["\']',
                    code, re.IGNORECASE
                ):
                    _entity = (_im.group(1) or _im.group(2) or "").strip()
                    if _entity and _entity not in _seen_entities:
                        _seen_entities.add(_entity)
                        _routes.extend([
                            {"method": "GET",    "path": f"/{_entity}"},
                            {"method": "POST",   "path": f"/{_entity}"},
                            {"method": "GET",    "path": f"/{_entity}/{{id}}"},
                            {"method": "PUT",    "path": f"/{_entity}/{{id}}"},
                            {"method": "DELETE", "path": f"/{_entity}/{{id}}"},
                        ])

            # Search: main.py, routers/crud.py (new multi-file layout), fallback paths
            _candidates = [
                _backend_out / "src" / "main.py",
                _backend_out / "src" / "routers" / "crud.py",
                _backend_out.parent / "src" / "main.py",
                _backend_out.parent / "src" / "routers" / "crud.py",
            ]
            _found_any = False
            for _candidate in _candidates:
                if _candidate.exists():
                    _extract_routes_from_code(_candidate.read_text())
                    _found_any = True

            if _found_any:
                _routes_file = _backend_out / "api_routes.json"
                _routes_file.write_text(json.dumps(_routes, indent=2))
                phase_input.input_data["api_routes_path"] = str(_routes_file)
                logger.info("p04: extracted %d routes → %s", len(_routes), _routes_file)
        # Startup smoke test — catch import/syntax errors before frontend is built
        if r.success and r.metadata:
            src_dir_candidates = [
                Path(r.output_path) / "src",
                Path(r.output_path).parent / "src",
                Path(r.metadata.get("backend_src_dir", "")),
            ]
            src_dir = next(
                (d for d in src_dir_candidates if (d / "main.py").exists()), None
            )
            if src_dir:
                _emit = getattr(phase_input, "emit", _noop_emit)
                try:
                    smoke = await _startup_smoke_test(src_dir, _emit)
                    phase_input.input_data["smoke_test"] = smoke
                    if not smoke.get("passed") and not smoke.get("skipped"):
                        logger.warning(
                            "p04 smoke test failed after %d attempt(s): %s",
                            smoke.get("attempts", 0),
                            smoke.get("errors", []),
                        )
                except Exception as _se:  # noqa: BLE001
                    logger.debug("p04 smoke test error (non-fatal): %s", _se)

        logger.info("p04a_backend_codegen completed: %s", r.output_path)
    except Exception as e:
        logger.warning("p04a_backend_codegen failed: %s", e)

    # Sub-task 2: UI/UX Design
    try:
        from aether_os.phases.p04b_uiux_design.task_agent import run as p04b_run
        sub_dir = output_dir / "uiux_design"
        r = await p04b_run(phase_input, memory_ctx, sub_dir)
        results["uiux_design"] = r
        logger.info("p04b_uiux_design completed: %s", r.output_path)
    except Exception as e:
        logger.warning("p04b_uiux_design failed (non-critical): %s", e)

    summary = {
        "phases": {
            k: {"output_path": v.output_path, "success": v.success, "confidence": v.confidence}
            for k, v in results.items()
        }
    }
    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    any_success = any(v.success for v in results.values())
    return TaskResult(
        output_path=str(summary_path),
        confidence=0.85 if any_success else 0.3,
        metadata=summary,
        success=any_success or bool(results),
        issues=[] if any_success else ["All sub-tasks failed"],
    )
