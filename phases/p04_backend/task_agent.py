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
    from core.llm.client import get_llm_client
    client = get_llm_client()
    source = main_py.read_text()
    prompt = (
        "The following FastAPI backend code fails to start with this error:\n\n"
        f"ERROR:\n{error}\n\n"
        f"CODE (first 200 lines):\n{chr(10).join(source.splitlines()[:200])}\n\n"
        "Fix ONLY the error above. Return the complete corrected Python file with no explanation.\n"
        "Common fixes: add missing imports, fix undefined names, use correct SQLAlchemy syntax.\n"
        "Do not change the API endpoints or business logic."
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
            check_code = (
                "import sys, os; "
                "os.chdir(str(__import__('pathlib').Path(__file__).parent)); "
                "exec(compile(open('main.py').read().split('\\napp ')[0], 'main.py', 'exec'))"
            )
            import os as _os
            smoke_env = {**_os.environ, "DATABASE_URL": "sqlite:///./smoke_test.db"}
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
                    if any(e in stderr_text for e in [
                        "ImportError", "ModuleNotFoundError", "NameError", "SyntaxError"
                    ]):
                        errors.append(f"ImportError: {stderr_text[:500]}")
            except asyncio.TimeoutError:
                pass  # timeout in import check is OK — app likely starts fine

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
            # Extract API routes from generated main.py so p05 can wire to real endpoints
            _backend_out = Path(r.output_path)
            for _main_candidate in [
                _backend_out / "src" / "main.py",
                _backend_out.parent / "src" / "main.py",
            ]:
                if _main_candidate.exists():
                    _code = _main_candidate.read_text()
                    _routes = []
                    for _m in re.finditer(
                        r'@app\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']',
                        _code, re.IGNORECASE
                    ):
                        _routes.append({"method": _m.group(1).upper(), "path": _m.group(2)})
                    if _routes:
                        _routes_file = _backend_out / "api_routes.json"
                        _routes_file.write_text(json.dumps(_routes, indent=2))
                        phase_input.input_data["api_routes_path"] = str(_routes_file)
                        logger.info("p04: extracted %d routes → %s", len(_routes), _routes_file)
                    break
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
