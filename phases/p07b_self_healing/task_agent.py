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

MAX_ATTEMPTS = 3
TEST_TIMEOUT = 60
LLM_TIMEOUT = 45


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
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

        msg = f"🔧 [p07b_self_healing] Tests failing — asking Ollama for fix..."
        logger.info(msg)
        await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg})

        msg2 = f"🔧 [p07b_self_healing] Attempt {attempt}/{MAX_ATTEMPTS} — applying fix..."
        logger.info(msg2)
        await emit({"type": "llm_chunk", "phase": "p07b_self_healing", "text": msg2})

        fix = await _get_fix(main_py, test_file, last_output)
        if not fix:
            logger.warning("[p07b_self_healing] LLM returned no fix for attempt %d", attempt)
            continue

        # Validate syntax before applying
        try:
            ast.parse(fix)
        except SyntaxError as e:
            logger.warning("[p07b_self_healing] LLM fix has syntax error: %s", e)
            continue

        main_py.write_text(fix)

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
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest",
            str(test_file), "-v", "--tb=short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(test_file.parent.parent),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TEST_TIMEOUT)
        output = stdout.decode() + stderr.decode()
        return {"passed": proc.returncode == 0, "output": output}
    except asyncio.TimeoutError:
        return {"passed": False, "output": f"pytest timed out after {TEST_TIMEOUT}s"}
    except Exception as e:
        return {"passed": False, "output": str(e)}


async def _get_fix(main_py: Path, test_file: Path, failure_output: str) -> Optional[str]:
    from aether_os.core.llm.client import get_llm_client

    prompt = f"""You are a Python bug fixer. Fix the code so the tests pass.

CURRENT CODE (main.py):
{main_py.read_text()[:2000]}

TEST FILE:
{test_file.read_text()[:1000]}

TEST FAILURE:
{failure_output[:1000]}

Return ONLY the fixed Python code for main.py.
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
