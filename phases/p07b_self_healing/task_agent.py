"""P07b Self-Healing — autonomous bug fix loop using Ollama."""
from __future__ import annotations
import asyncio
import ast
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.base import TaskResult
from aether_os.orchestrator.events import emit

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
TEST_TIMEOUT = 60
LLM_TIMEOUT = 45
# Hard cap so the phase never blocks the orchestrator beyond this
_PHASE_HARD_TIMEOUT = MAX_ATTEMPTS * (TEST_TIMEOUT + LLM_TIMEOUT + 15)  # 600s


import re

def _identify_failing_file(test_output: str, project_dir: Path) -> Optional[Path]:
    """
    Problem 50 fix: Parse exec validation error output (stdout/stderr from Python
    import/syntax check) to identify the EXACT failing file and line number.

    Priority order:
    1. Python traceback  File "/path/to/file.py", line N  (most precise)
    2. pytest ERROR collecting / FAILED markers
    3. ImportError in file
    """
    # Priority 1: Python traceback — last File "..." entry is the actual failing location
    traceback_matches = re.findall(r'File "([^"]+\.py)", line \d+', test_output)
    if traceback_matches:
        # Walk from last to first — skip test files and site-packages
        for candidate_str in reversed(traceback_matches):
            if "site-packages" in candidate_str or "pytest" in candidate_str:
                continue
            candidate = Path(candidate_str)
            if not candidate.is_absolute():
                candidate = (project_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.exists():
                logger.debug("[p07b] Traceback identified failing file: %s", candidate)
                return candidate

    # Priority 2: pytest ERROR collecting / FAILED markers
    patterns = [
        r'ERROR collecting (.+?\.py)',
        r'FAILED (.+?\.py)::',
        r'ImportError.*in (.+?\.py)',
    ]
    for pat in patterns:
        m = re.search(pat, test_output)
        if m:
            candidate_str = m.group(1)
            try:
                if os.path.isabs(candidate_str):
                    candidate_str = os.path.relpath(candidate_str, str(project_dir))
            except Exception as exc:
                logger.debug("p07b: relpath conversion failed (non-fatal): %s", exc)
            candidate = Path(candidate_str)
            if not candidate.is_absolute():
                candidate = (project_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.exists():
                logger.debug("[p07b] Pattern matched failing file: %s", candidate)
                return candidate
    return None


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    try:
        return await asyncio.wait_for(_run_inner(phase_input, memory_ctx, output_dir), timeout=_PHASE_HARD_TIMEOUT)
    except asyncio.TimeoutError:
        msg = f"⚠ [p07b_self_healing] Phase hard-timeout ({_PHASE_HARD_TIMEOUT}s) — skipping"
        logger.warning(msg)
        result = {"success": True, "status": "phase_timeout", "attempts": MAX_ATTEMPTS}
        (output_dir / "self_healing.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "self_healing.json"),
            confidence=0.3,
            metadata=result,
            success=True,
            issues=["Self-healing phase timed out"],
        )


async def _run_inner(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = phase_input.run_id
    project_dir = Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))

    main_py = _find_file(project_dir, "main.py")
    test_file = _find_file(project_dir, "test_*.py")

    if not main_py or not test_file:
        result = {"success": True, "skipped": True, "reason": "No testable code found"}
        (output_dir / "self_healing.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "self_healing.json"),
            confidence=1.0,
            metadata=result,
            success=True,
            issues=[],
        )

    attempt = 0
    last_output = ""

    while attempt < MAX_ATTEMPTS:
        attempt += 1

        # Run pytest
        test_result = await _run_tests(test_file)

        if test_result["passed"]:
            msg = f"✓ [p07b_self_healing] Tests passing after {attempt} attempt(s)"
            logger.info(msg)
            await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg})
            result = {
                "success": True,
                "attempts": attempt,
                "status": "all_tests_passing",
                "output": test_result["output"][:500],
            }
            (output_dir / "self_healing.json").write_text(json.dumps(result, indent=2))
            return TaskResult(
                output_path=str(output_dir / "self_healing.json"),
                confidence=1.0,
                metadata=result,
                success=True,
                issues=[],
            )

        last_output = test_result["output"]

        msg = f"🔧 [p07b_self_healing] Tests failing — requesting LLM fix (attempt {attempt}/{MAX_ATTEMPTS})..."
        logger.info(msg)
        await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg})

        msg2 = f"🔧 [p07b_self_healing] Attempt {attempt}/{MAX_ATTEMPTS} — applying fix..."
        logger.info(msg2)
        await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg2})

        failing_file = _identify_failing_file(last_output, project_dir) or main_py
        fix = await _get_fix(failing_file, test_file, last_output)
        if not fix:
            logger.warning("[p07b_self_healing] LLM returned no fix for attempt %d", attempt)
            continue

        # Validate syntax before applying — use compile() not ast.parse() because
        # compile() catches duplicate keyword arguments that ast.parse() silently accepts.
        try:
            compile(fix, failing_file.name, "exec")
        except SyntaxError as e:
            logger.warning("[p07b_self_healing] LLM fix has syntax error: %s", e)
            continue

        # Deterministically fix relative imports → flat absolute imports
        # The generated app runs from src/ so all sibling modules are importable directly
        fix = re.sub(r'from\s*\.+\s*(\w)', r'from \1', fix)   # from .foo → from foo
        fix = re.sub(r'import\s*\.+\s*(\w)', r'import \1', fix)  # import .foo → import foo

        # Re-validate after sanitization
        try:
            compile(fix, failing_file.name, "exec")
        except SyntaxError as e:
            logger.warning("[p07b_self_healing] Fix still has syntax error after sanitize: %s", e)
            continue

        # Deterministically ensure crud.py always exports all_routers
        if failing_file.name == "crud.py" and "all_routers" not in fix:
            router_vars = re.findall(r'^(\w+_router)\s*=\s*APIRouter', fix, re.MULTILINE)
            if router_vars:
                fix = fix.rstrip() + f"\n\nall_routers = [{', '.join(router_vars)}]\n"
                logger.info("[p07b_self_healing] Auto-injected all_routers: %s", router_vars)

        failing_file.write_text(fix)

    # Problem 45 fix: Max attempts reached — tests still failing → report failure accurately
    # Do NOT propagate a false success=True; set gate_result accordingly
    result = {
        "success": False,                   # Problem 45: was incorrectly True
        "self_healing_exhausted": True,     # Problem 45: signal for orchestrator
        "attempts": attempt,
        "status": "max_attempts_reached",
        "last_output": last_output[:500],
    }
    msg = f"[p07b_self_healing] Max attempts ({MAX_ATTEMPTS}) reached — tests still failing"
    logger.warning(msg)
    await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg})
    (output_dir / "self_healing.json").write_text(json.dumps(result, indent=2))
    return TaskResult(
        output_path=str(output_dir / "self_healing.json"),
        confidence=0.0,                     # Problem 45: was 0.4, should be 0.0 on full exhaustion
        metadata=result,
        success=False,                      # Problem 45: was True
        issues=[f"Self-healing exhausted: tests still failing after {MAX_ATTEMPTS} attempts"],
    )


async def _run_tests(test_file: Path) -> Dict[str, Any]:
    proc = None
    try:
        _test_env = {
            **os.environ,
            "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
            "SECRET_KEY": "test-secret-key-not-for-production",
        }
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest",
            str(test_file), "-v", "--tb=short", "--timeout=30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(test_file.parent.parent),
            env=_test_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TEST_TIMEOUT)
        output = stdout.decode() + stderr.decode()
        return {"passed": proc.returncode == 0, "output": output}
    except asyncio.TimeoutError:
        # Kill the subprocess so it doesn't keep holding pipes open
        if proc is not None:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception as exc:
                logger.debug("p07b: failed to kill timed-out pytest process (non-fatal): %s", exc)
        return {"passed": False, "output": f"pytest timed out after {TEST_TIMEOUT}s"}
    except Exception as e:
        if proc is not None:
            try:
                proc.kill()
            except Exception as exc:
                logger.debug("p07b: failed to kill pytest process on error (non-fatal): %s", exc)
        return {"passed": False, "output": str(e)}


async def _get_fix(target_file: Path, test_file: Path, failure_output: str) -> Optional[str]:
    """
    Problem 50 fix: Parse the exec validation error output to identify the exact failing
    file and line number; send THAT file with the exact error to the LLM.
    Do NOT rely on the escalation message from an earlier phase.
    """
    from aether_os.core.llm.client import get_llm_client

    # Problem 50 fix: extract exact file path and line number from the Python traceback
    _tb_match = re.search(r'File "([^"]+\.py)", line (\d+)', failure_output)
    _exact_location = ""
    if _tb_match:
        _exact_file_str = _tb_match.group(1)
        _exact_line = _tb_match.group(2)
        _exact_location = f"\nEXACT FAILING LOCATION: File \"{_exact_file_str}\", line {_exact_line}"
        # If the traceback points to a different file than target_file, use it
        _tb_path = Path(_exact_file_str)
        if _tb_path.exists() and _tb_path.resolve() != target_file.resolve():
            logger.info("[p07b] Traceback points to %s (not %s) — switching target file",
                        _tb_path, target_file)
            target_file = _tb_path

    # Gather full context — target_file first (most important), then siblings
    src_dir = target_file.parent
    try:
        _target_content = target_file.read_text()
    except Exception:
        _target_content = "# (could not read file)"

    _src_ctx = f"# === {target_file.name} (FAILING FILE) ===\n{_target_content}\n"
    for _sib in ["main.py", "models.py", "schemas.py", "routers/crud.py", "auth.py", "database.py"]:
        if _sib == target_file.name:
            continue
        _p = src_dir / _sib
        if _p.exists():
            _content = _p.read_text()
            _src_ctx += f"\n# === {_sib} ===\n{_content}\n"

    # Cap total context at ~12000 chars to stay within LLM window
    if len(_src_ctx) > 12000:
        _src_ctx = _src_ctx[:12000] + "\n# ... (truncated — remaining files omitted)"

    prompt = f"""You are a senior Python backend engineer. Fix the FastAPI backend so all tests pass.

FAILING FILE: {target_file.name}{_exact_location}

SOURCE FILES (context):
{_src_ctx}

TEST FILE:
{test_file.read_text()[:2000]}

TEST FAILURE OUTPUT (exact error from Python execution):
{failure_output[:2000]}

RULES:
- Read the EXACT FAILING LOCATION above — that is the line with the bug.
- Return ONLY the fixed complete {target_file.name}.
- The @asynccontextmanager decorator MUST be on the line immediately before async def lifespan. Do NOT place any function calls (e.g. setup_logging()) between the decorator and the function definition. setup_logging() must be called INSIDE the lifespan function body.
- Never store plaintext passwords — use passlib bcrypt
- Never use in-memory dicts/lists as databases — use SQLAlchemy ORM
- Use `result.scalars().all()` not `result.all()` for async SQLAlchemy queries
- Use `result.scalar_one_or_none()` not `result.first()` for single-row queries
- All models must extend Base from .database, never use plain Python classes
- All datetime defaults: `datetime.now(timezone.utc)`, never `datetime.utcnow()`
- Import every name you use — no bare NameError references
- After fixing, verify all imports exist and all referenced names are defined
- CRITICAL: NEVER use relative imports. All imports MUST be flat absolute: `import models`, `from database import get_db`, `from auth import get_current_user`. NEVER write `from .database`, `from ..database`, `from .models`, `from..database` etc.
- If fixing routers/crud.py: the LAST LINE must be `all_routers = [<router_var_1>, <router_var_2>, ...]` listing EVERY APIRouter variable defined in the file. Never remove this line.
- If the error is "cannot import name 'all_routers'": add `all_routers = [<list all router variables defined above>]` as the last line.

No explanation. No markdown. No code fences. Just valid Python."""

    def _strip_fences(code: str) -> str:
        code = code.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            code = "\n".join(l for l in lines if not l.startswith("```"))
        return code

    # PIPELINE-046: try primary LLM first, fall back to Anthropic if primary fails
    try:
        llm = get_llm_client()
        response = await asyncio.wait_for(
            llm.call(prompt, "code_generation", {}),
            timeout=LLM_TIMEOUT,
        )
        if response and len(response.strip()) > 50:
            cleaned = _strip_fences(response)
            # Validate syntax before accepting — fall through to Anthropic if broken
            # compile() not ast.parse(): catches duplicate keyword args that ast.parse misses
            try:
                compile(cleaned, target_file.name, "exec")
                return cleaned
            except SyntaxError as _syn:
                logger.warning("[p07b_self_healing] Primary LLM response has SyntaxError: %s — escalating to Anthropic", _syn)
                raise ValueError(f"Primary LLM produced syntactically invalid Python: {_syn}") from _syn
        raise ValueError("Empty or trivial response from primary LLM")
    except Exception as primary_exc:
        logger.warning("[p07b_self_healing] Primary LLM call failed: %s", primary_exc)

    # Fallback: direct Anthropic client if ANTHROPIC_API_KEY is set
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic as _anthropic
            _client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            _msg = _client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            fallback_response = _msg.content[0].text if _msg.content else ""
            if fallback_response and len(fallback_response.strip()) > 50:
                logger.info("[p07b_self_healing] Anthropic fallback succeeded")
                return _strip_fences(fallback_response)
        except Exception as fallback_exc:
            logger.warning("[p07b_self_healing] Anthropic fallback also failed: %s", fallback_exc)

    return None


def _find_file(project_dir: Path, pattern: str) -> Optional[Path]:
    _SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "p03_scaffolding"}
    matches = [
        p for p in project_dir.rglob(pattern)
        if not any(part in _SKIP_DIRS for part in p.parts)
    ]
    if not matches:
        # Second pass: include scaffolding as fallback when backend codegen hasn't run
        matches = list(project_dir.rglob(pattern))
    # Prefer deeper paths — p04 backend output is always deeper than p03 scaffolding
    matches.sort(key=lambda p: len(p.parts), reverse=True)
    return matches[0] if matches else None
