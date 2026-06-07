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
    """Extract the file path from pytest's error output (FIX 18)."""
    # Pattern: "ERROR collecting path/to/file.py" or "FAILED path/to/test.py::test_name"
    patterns = [
        r'ERROR collecting (.+?\.py)',
        r'FAILED (.+?\.py)::',
        r'ImportError.*in (.+?\.py)',
        r'File "(.+?\.py)", line \d+',
    ]
    for pat in patterns:
        m = re.search(pat, test_output)
        if m:
            candidate = Path(m.group(1))
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            if candidate.exists():
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
                confidence=0.95,
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

        # Validate syntax before applying
        try:
            ast.parse(fix)
        except SyntaxError as e:
            logger.warning("[p07b_self_healing] LLM fix has syntax error: %s", e)
            continue

        failing_file.write_text(fix)

    # Max attempts reached — non-blocking, still success
    result = {
        "success": True,
        "attempts": attempt,
        "status": "max_attempts_reached",
        "last_output": last_output[:500],
    }
    msg = f"⚠ [p07b_self_healing] Max attempts ({MAX_ATTEMPTS}) reached — tests still failing"
    logger.warning(msg)
    await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg})
    (output_dir / "self_healing.json").write_text(json.dumps(result, indent=2))
    return TaskResult(
        output_path=str(output_dir / "self_healing.json"),
        confidence=0.4,
        metadata=result,
        success=True,  # Non-blocking
        issues=[f"Tests still failing after {MAX_ATTEMPTS} attempts"],
    )


async def _run_tests(test_file: Path) -> Dict[str, Any]:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest",
            str(test_file), "-v", "--tb=short", "--timeout=30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(test_file.parent.parent),
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
            except Exception:
                pass
        return {"passed": False, "output": f"pytest timed out after {TEST_TIMEOUT}s"}
    except Exception as e:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        return {"passed": False, "output": str(e)}


async def _get_fix(target_file: Path, test_file: Path, failure_output: str) -> Optional[str]:
    from aether_os.core.llm.client import get_llm_client

    # Gather full context — all generated source files matter for diagnosing the failure
    src_dir = target_file.parent
    _src_ctx = f"# === {target_file.name} ===\n{target_file.read_text()}\n"
    for _sib in ["main.py", "models.py", "schemas.py", "routers/crud.py", "auth.py", "database.py"]:
        if _sib == target_file.name: continue
        _p = src_dir / _sib
        if _p.exists():
            _content = _p.read_text()
            _src_ctx += f"\n# === {_sib} ===\n{_content}\n"

    # Cap total context at ~12000 chars to stay within LLM window
    if len(_src_ctx) > 12000:
        _src_ctx = _src_ctx[:12000] + "\n# ... (truncated — remaining files omitted)"

    prompt = f"""You are a senior Python backend engineer. Fix the FastAPI backend so all tests pass.

FAILING FILE: {target_file.name}

SOURCE FILES (context):
{_src_ctx}

TEST FILE:
{test_file.read_text()[:2000]}

TEST FAILURE OUTPUT:
{failure_output[:2000]}

RULES:
- Return ONLY the fixed complete {target_file.name}.
- Never store plaintext passwords — use passlib bcrypt
- Never use in-memory dicts/lists as databases — use SQLAlchemy ORM
- Use `result.scalars().all()` not `result.all()` for async SQLAlchemy queries
- Use `result.scalar_one_or_none()` not `result.first()` for single-row queries
- All models must extend Base from .database, never use plain Python classes
- All datetime defaults: `datetime.now(timezone.utc)`, never `datetime.utcnow()`
- Import every name you use — no bare NameError references
- After fixing, verify all imports exist and all referenced names are defined

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
            return _strip_fences(response)
        raise ValueError("Empty or trivial response from primary LLM")
    except Exception as primary_exc:
        logger.warning("[p07b_self_healing] Primary LLM call failed: %s", primary_exc)

    # Fallback: direct Anthropic client if ANTHROPIC_API_KEY is set
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic as _anthropic
            _client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            _msg = _client.messages.create(
                model="claude-haiku-4-5",
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
