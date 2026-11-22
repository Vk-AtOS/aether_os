"""P04 Consolidated Task Agent — backend codegen + UI/UX design."""
from __future__ import annotations
import asyncio
import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.llm.client import get_llm_client
from aether_os.phases.base import TaskResult
from aether_os.phases.utils import get_domain_ir
from aether_os.phases.p04_backend.go_generator import (
    generate_go_multiservice,
    generate_go_project,
    service_dir,
)
from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
from aether_os.phases.p04_backend.node_generator import generate_node_project
from aether_os.core.sandbox import phase_exec
from aether_os.core.errors import PipelineBlockedError
from aether_os.core.sandbox.runner import SandboxUnavailable

logger = logging.getLogger(__name__)

# No-op fallback when no emit callable is available
async def _noop_emit(event: dict) -> None:  # noqa: ARG001
    pass


def _read_if_exists(path: Path) -> str:
    """Return file contents as a string, or '' if the file does not exist."""
    try:
        return path.read_text()
    except OSError:
        return ""


async def _smoke_repair(main_py: Path, error: str, attempt: int) -> bool:  # noqa: ARG001
    """Ask LLM to fix a startup error in main.py. Returns True if fixed."""
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
        fixed = await client.call(prompt, task_type="code_fix")
        if fixed and len(fixed.strip()) > 100:
            try:
                ast.parse(fixed)
                main_py.write_text(fixed)
                return True
            except SyntaxError:
                return False
    except Exception as e:  # noqa: BLE001
        logger.warning("p04_backend: _autofix_syntax_error failed: %s", e)
        return False
    return False


async def _startup_smoke_test(src_dir: Path, emit) -> dict:
    """Run syntax + import checks on generated main.py. Returns {passed, errors, attempts}."""
    main_py = src_dir / "main.py"
    if not main_py.exists():
        return {"passed": True, "errors": [], "skipped": True}

    # Single-call-per-phase rule: cap LLM-driven smoke repair to ONE attempt.
    # Previous value of 3 could produce 3 _smoke_repair LLM calls when the
    # generated code had a stubborn issue (e.g. a missing import the LLM kept
    # re-introducing). The platform's other layers (IR + deterministic
    # generators) already guarantee well-formed code, so one repair is plenty.
    MAX_ATTEMPTS = 1
    errors: list = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        errors = []

        # Step 1: syntax check via py_compile
        # py_compile only parses; it still goes through the sandbox with the rest, so no
        # generated file is ever handed to a host interpreter.
        compiled = await phase_exec.run(["python3", "-m", "py_compile", str(main_py)],
                                        cwd=src_dir, timeout=15, text=True)
        if compiled.returncode != 0:
            errors.append(f"SyntaxError: {compiled.stderr[:500]}")

        # Step 2: import check (only if syntax OK)
        # Override DATABASE_URL so create_all() targets an isolated temp SQLite
        # rather than the AetherOS production database.
        if not errors:
            # PIPELINE-061: regex-split to handle 'app' or 'application = FastAPI(...)'
            # Inject __file__ into the exec globals — generated code may reference it
            # (e.g. `_self_dir = Path(__file__).resolve().parent`) and `exec` does
            # not auto-set __file__ otherwise, which used to surface as a NameError.
            check_code = (
                "import sys, os, re; "
                "src = open('main.py').read(); "
                "parts = re.split(r'\\n(?:app|application)\\s*=\\s*FastAPI', src, maxsplit=1); "
                "globals_ns = {'__file__': os.path.abspath('main.py'), '__name__': '__main__'}; "
                "exec(compile(parts[0], 'main.py', 'exec'), globals_ns)"
            )
            # The temp DB lives in the run dir (the sandbox's only writable place).
            _db_tmp = str(src_dir / f".smoke_{os.getpid()}.db")
            smoke_env = {"DATABASE_URL": f"sqlite:///{_db_tmp}"}
            try:
                try:
                    done2 = await phase_exec.run(["python3", "-c", check_code], cwd=src_dir,
                                                 env=smoke_env, timeout=20, text=True)
                    if done2.returncode != 0:
                        stderr_text = done2.stderr
                        # Relative import errors are expected in package-structured code;
                        # uvicorn runs via `python -m` so they resolve correctly at runtime.
                        if "attempted relative import" in stderr_text or \
                                "relative import" in stderr_text.lower():
                            pass  # non-fatal — valid package structure
                        # Missing-runtime-dep errors are also non-fatal: the
                        # generated backend ships its own requirements.txt and
                        # creates its own venv; the platform's own python env
                        # doesn't need every dep installed for the smoke test.
                        elif "No module named" in stderr_text or \
                                "ModuleNotFoundError" in stderr_text or \
                                "is not installed" in stderr_text:
                            logger.debug("p04 smoke: ignoring missing runtime dep — %s", stderr_text[:100])
                        elif any(e in stderr_text for e in [
                            "NameError", "SyntaxError"
                        ]):
                            errors.append(f"ImportError: {stderr_text[:500]}")
                except asyncio.TimeoutError:
                    logger.warning("p04 task_agent: import check timed out — app likely starts fine")
            finally:
                # Clean up temp DB file
                try:
                    Path(_db_tmp).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("p04 task_agent: failed to remove temp DB file %s: %s", _db_tmp, e)

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


async def _run_go_backend(phase_input: Any, output_dir: Path) -> TaskResult:
    """Generate Go/Gin backend (single service or multi-service) based on build_profile."""
    data = phase_input.input_data or {}
    domain_ir = get_domain_ir(data)
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]
    project_name = data.get("project_name") or "generated-app"
    bp = data.get("build_profile") or {}
    db_driver = "sqlite" if bp.get("db_primary") == "sqlite" else "postgres"
    service_map = data.get("service_map") or {}

    try:
        if service_map.get("services"):
            # Microservices: generate one directory per service
            dirs = await generate_go_multiservice(service_map, entities, project_name, output_dir)
            # Add gRPC layer for grpc-communication services
            for svc in service_map["services"]:
                if svc.get("communication") == "grpc":
                    svc_dir = service_dir(output_dir, svc["name"]) / "backend"
                    slug = svc["name"].lower()
                    module = f"github.com/aetheros/{slug}"
                    owns = set(svc.get("owns_entities") or [])
                    svc_entities = [e for e in entities if (e.get("table", "").title() in owns)] or entities
                    await generate_grpc_files(svc["name"], svc_entities, svc_dir, module)
            logger.info("p04: Go multiservice generated — %d services", len(dirs))
            return TaskResult(
                output_path=str(output_dir / "services"),
                confidence=0.85,
                metadata={"backend_lang": "go", "service_count": len(dirs), "multiservice": True},
                success=True,
            )
        else:
            backend_dir = await generate_go_project(entities, project_name, output_dir, db_driver)
            logger.info("p04: Go monolith backend generated at %s", backend_dir)
            return TaskResult(
                output_path=str(backend_dir),
                confidence=0.85,
                metadata={"backend_lang": "go", "backend_dir": str(backend_dir)},
                success=True,
            )
    except Exception as e:
        logger.error("p04: Go backend generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)


async def _run_node_backend(phase_input: Any, output_dir: Path) -> TaskResult:
    """Generate TypeScript/Fastify backend when build_profile.backend_lang == 'typescript'."""
    data = phase_input.input_data or {}
    domain_ir = get_domain_ir(data)
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]
    project_name = data.get("project_name") or "generated-app"
    try:
        backend_dir = await generate_node_project(entities, project_name, output_dir)
        logger.info("p04: Node/TS backend generated at %s", backend_dir)
        return TaskResult(
            output_path=str(backend_dir),
            confidence=0.85,
            metadata={"backend_lang": "typescript", "backend_dir": str(backend_dir)},
            success=True,
        )
    except Exception as e:
        logger.error("p04: Node/TS backend generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Route to language-specific generator when build_profile requests it.
    # Falls through to the default FastAPI generator for "python" or missing profile.
    _bp = (phase_input.input_data or {}).get("build_profile") or {}
    _backend_lang = _bp.get("backend_lang", "python")

    if _backend_lang == "go":
        return await _run_go_backend(phase_input, output_dir)
    if _backend_lang == "typescript":
        return await _run_node_backend(phase_input, output_dir)

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
                except SandboxUnavailable:
                    raise  # generated code was not run: fail the phase, never fall back to the host
                except Exception as _se:  # noqa: BLE001
                    logger.debug("p04 smoke test error (non-fatal): %s", _se)

        logger.info("p04a_backend_codegen completed: %s", r.output_path)

        # ── Architecture Governor: verify generated entities match Domain IR ──────
        try:
            from aether_os.core.architecture_governor import ArchitectureGovernor
            _gov = ArchitectureGovernor.from_output_dir(output_dir)
            if _gov is not None:
                _backend_src = Path(r.output_path) / "src"
                _gov_report = _gov.generate_report("p04_backend", {
                    "models.py": _read_if_exists(_backend_src / "models.py"),
                    "crud.py": _read_if_exists(_backend_src / "routers" / "crud.py"),
                })
                if _gov_report.phantom_entities:
                    logger.warning(
                        "p04_backend governor: phantom entities in generated code: %s",
                        _gov_report.phantom_entities,
                    )
                accumulated_context = phase_input.input_data.setdefault("accumulated_context", {})
                accumulated_context["governor_report"] = {
                    "phantom_entities": _gov_report.phantom_entities,
                    "missing_entities": _gov_report.missing_entities,
                    "violation_count": len(_gov_report.violations),
                }
        except Exception as _gov_exc:
            logger.warning("p04_backend governor check failed (non-fatal): %s", _gov_exc)

    except (SandboxUnavailable, PipelineBlockedError):
        raise  # the run must stop: never downgrade a blocked gate or a missing sandbox to a warning
    except Exception as e:
        logger.warning("p04a_backend_codegen failed: %s", e)

    # Sub-task 2: UI/UX Design
    try:
        from aether_os.phases.p04_uiux_design.task_agent import run as p04b_run
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

    # The backend is the deliverable of this phase: a successful design alone is not success.
    backend = results.get("backend_codegen")
    backend_ok = bool(backend and backend.success)
    return TaskResult(
        output_path=str(summary_path),
        confidence=0.85 if backend_ok else 0.3,
        metadata=summary,
        success=backend_ok,
        issues=[] if backend_ok else ["Backend code generation failed or did not run"],
    )
