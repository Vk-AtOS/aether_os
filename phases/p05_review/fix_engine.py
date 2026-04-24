"""
AetherOS — Fix Engine (Phase 05 Review)
Migrated from Aether-one/aetherone/fix_engine.py.

BUG 10 FIX:
  - Removed _auto_fix_syntax() rule-based strategy.
    The rule "append None to lines ending with =" is semantically wrong
    for type hints and augmented assignments (x: int = → x: int = None).
  - Removed _auto_fix_runtime() NameError rule.
    Setting undefined variables to None masks real bugs and creates
    silent None reference errors downstream.
  - Only the LLM-based fix path (propose_python_fix) is used now.
"""
from __future__ import annotations
import logging
import os
from typing import Tuple

logger = logging.getLogger(__name__)


def _load_source(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def _save_source(file_path: str, content: str) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def auto_fix_python_file(project_path: str, file_path: str) -> Tuple[bool, str, str]:
    """
    Attempt to automatically fix simple syntax or runtime errors in a Python file.
    Uses LLM-based fix only (rule-based fixes removed — see Bug 10 in audit).

    Returns:
        (changed: bool, message: str, snapshot_path: str)
    """
    # Import these lazily to avoid circular imports at module load
    try:
        from aether_os.core.sandbox.python_tools import check_syntax, run_python_file
    except ImportError:
        logger.warning("python_tools not available, using subprocess fallback")
        check_syntax = _fallback_check_syntax
        run_python_file = _fallback_run_python

    file_abs = os.path.abspath(os.path.expanduser(file_path))
    project_abs = os.path.abspath(os.path.expanduser(project_path))

    # 1. Syntax phase
    ok_syntax, syntax_msg = check_syntax(file_abs)
    if not ok_syntax:
        source = _load_source(file_abs)

        # LLM-only fix (Bug 10 fix: no rule-based path)
        ai_ok, ai_source, ai_note = _llm_fix(source, syntax_msg, file_abs)
        if not ai_ok:
            return False, f"Syntax error — LLM fix not available: {syntax_msg} | {ai_note}", ""

        snapshot_path = _snapshot(project_abs, file_abs)
        _save_source(file_abs, ai_source)

        ok_after, after_msg = check_syntax(file_abs)
        if not ok_after:
            return True, f"LLM syntax fix applied but still failing: {after_msg}", snapshot_path

        return True, ai_note, snapshot_path

    # 2. Runtime phase
    ok_run, run_msg = run_python_file(file_abs)
    if ok_run:
        return False, "No syntax or runtime errors detected. Nothing to fix.", ""

    source = _load_source(file_abs)

    # LLM-only fix (Bug 10 fix: no rule-based NameError path)
    ai_ok, ai_source, ai_note = _llm_fix(source, run_msg, file_abs)
    if not ai_ok:
        return False, f"Runtime error — LLM fix not available: {run_msg} | {ai_note}", ""

    snapshot_path = _snapshot(project_abs, file_abs)
    _save_source(file_abs, ai_source)

    ok_after_run, after_run_msg = run_python_file(file_abs)
    if not ok_after_run:
        return True, f"LLM runtime fix applied but still failing: {after_run_msg}", snapshot_path

    return True, ai_note, snapshot_path


def _llm_fix(source: str, error_msg: str, file_path: str) -> Tuple[bool, str, str]:
    """Call LLM to propose a fix. Returns (ok, fixed_source, note)."""
    try:
        import asyncio
        from aether_os.core.llm.client import get_llm_client

        prompt = (
            f"Fix the following Python code. The error is:\n{error_msg}\n\n"
            f"Return ONLY the complete fixed Python code, no explanations.\n\n"
            f"Code:\n{source}"
        )

        async def _run() -> str:
            return await get_llm_client().call(prompt, task_type="code_generation")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _run())
                    fixed = future.result(timeout=120)
            else:
                fixed = loop.run_until_complete(_run())
        except Exception:
            fixed = asyncio.run(_run())

        if fixed and fixed.strip():
            return True, fixed.strip(), "LLM fix applied"
        return False, source, "LLM returned empty response"

    except Exception as exc:
        logger.warning("LLM fix failed: %s", exc)
        return False, source, f"LLM unavailable: {exc}"


def _snapshot(project_root: str, file_path: str) -> str:
    """Take a snapshot of file before patching. Returns snapshot path or empty string."""
    try:
        import shutil
        import time
        snap_dir = os.path.join(project_root, ".aether_snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        basename = os.path.basename(file_path)
        snap_path = os.path.join(snap_dir, f"{basename}.{int(time.time())}.bak")
        shutil.copy2(file_path, snap_path)
        return snap_path
    except Exception as exc:
        logger.warning("Snapshot failed: %s", exc)
        return ""


def _fallback_check_syntax(file_path: str) -> Tuple[bool, str]:
    import ast
    try:
        with open(file_path, "r") as f:
            ast.parse(f.read())
        return True, ""
    except SyntaxError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _fallback_run_python(file_path: str) -> Tuple[bool, str]:
    import subprocess
    result = subprocess.run(["python", file_path], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return True, ""
    return False, result.stderr
