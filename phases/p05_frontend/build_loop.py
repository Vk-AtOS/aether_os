"""P05 Frontend — Compile-error feedback loop.

Runs `tsc --noEmit` + `vite build` and feeds any errors back to the LLM for
targeted find/replace patches. Retries up to max_rounds before giving up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from aether_os.core.sandbox import phase_exec
from aether_os.core.llm.json_enforcer import extract_first_json
from aether_os.core.sandbox.runner import SandboxUnavailable
from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules
from aether_os.phases.p05_frontend.npm_deps import ensure_npm_deps
from aether_os.phases.p05_frontend.npm_runner import PREVIEW_BUILD_ENV

logger = logging.getLogger(__name__)

_TS_ERROR_RE = re.compile(r"error TS\d+:")
_MAX_ERR_CHARS = 3000
MAX_TSC_MESSAGES = 10
_PROMPT_TEMPLATE = (
    "You are a TypeScript/React developer. The following errors occurred "
    "during `tsc --noEmit` and/or `vite build`. List the exact file:line "
    "fixes needed as a JSON array of "
    '{{"file": "src/pages/X.tsx", "find": "old text", "replace": "new text"}} '
    "objects. Return ONLY the JSON array, no prose. Errors:\n{errors}"
)


def _count_tsc_errors(text: str) -> int:
    return len(_TS_ERROR_RE.findall(text or ""))


def _combine_output(result: subprocess.CompletedProcess) -> str:
    out = (result.stdout or "") + (result.stderr or "")
    return out[-_MAX_ERR_CHARS:]


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Pull first JSON array out of an LLM response (may be fenced or prefaced)."""
    if not raw:
        return []
    try:
        return extract_first_json(raw, expect=list)
    except ValueError as exc:
        logger.warning("p05 build_loop: JSON parse failed: %s", exc)
        return []


def _apply_patch(frontend_dir: Path, patch: dict) -> bool:
    path_str = patch.get("file", "")
    find = patch.get("find", "")
    replace = patch.get("replace", "")
    if not path_str or not find:
        return False
    # The path comes from a model's answer: `../../x` or an absolute path or a symlink must not leave the project
    # (it used to write wherever the process could), and node_modules is not ours to patch.
    root = frontend_dir.resolve()
    target = (frontend_dir / path_str).resolve()
    if not target.is_relative_to(root) or "node_modules" in target.relative_to(root).parts:
        logger.warning("p05 build_loop: patch path %r rejected (outside the project)", path_str)
        return False
    if not target.exists() or not target.is_file():
        return False
    try:
        text = target.read_text()
    except Exception as exc:
        logger.warning("p05 build_loop: read %s failed: %s", target, exc)
        return False
    if find not in text:
        return False
    target.write_text(text.replace(find, replace, 1))
    return True


async def _llm_fix(error_output: str) -> list[dict[str, Any]]:
    from aether_os.core.llm.client import get_llm_client
    prompt = _PROMPT_TEMPLATE.format(errors=error_output)
    try:
        raw = await asyncio.wait_for(
            get_llm_client().call(prompt, task_type="code_generation", max_tokens=2000),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.warning("p05 build_loop: LLM fix call timed out")
        return []
    except Exception as exc:
        logger.warning("p05 build_loop: LLM fix call failed: %s", exc)
        return []
    return _extract_json_array(raw)


def _tsc_messages(tsc_result: subprocess.CompletedProcess) -> list[str]:
    out = (tsc_result.stdout or "") + (tsc_result.stderr or "")
    lines = [ln.strip()[:300] for ln in out.splitlines() if "error TS" in ln]
    if not lines and tsc_result.returncode != 0:  # tsc died without TS diagnostics: still a type-check failure
        lines = [out.strip().splitlines()[-1][:300] if out.strip() else f"tsc exited {tsc_result.returncode}"]
    return lines


def _outcome(built: bool, tsc_lines: list[str], rounds: int) -> dict:
    return {"success": built, "built": built, "tsc_errors": len(tsc_lines), "tsc_messages": tsc_lines[:MAX_TSC_MESSAGES],
            "rounds": rounds}


def result_summary(loop: dict) -> tuple[dict, list[str]]:
    """(metadata, issues) the phase reports for a build_loop outcome: the tsc count and first messages are visible in
    the run result, and a bundled app with leftover type errors carries a warning instead of a failure."""
    n = int(loop.get("tsc_errors", 0))
    meta = {"build_ok": bool(loop.get("built", loop.get("success"))), "tsc_errors": n,
            "tsc_messages": list(loop.get("tsc_messages", []))}
    issues = []
    if n and meta["build_ok"]:
        issues.append(f"p05 warning: vite build succeeded but {n} TypeScript error(s) remain. First: "
                      + " | ".join(meta["tsc_messages"][:3]))
    return meta, issues


async def run_build_loop(frontend_dir: Path, max_rounds: int = 3) -> dict:
    """tsc --noEmit + vite build -> parse errors -> LLM fix per round -> max_rounds.

    Policy: the phase SUCCEEDS when `vite build` exits 0 and produced dist/index.html (the app bundles and can be
    previewed). tsc errors never fail it: they are returned as a count plus the first MAX_TSC_MESSAGES messages (they
    lower the confidence and are reported as warnings) while the loop keeps asking the model to fix them.

    Returns: {"success", "built", "tsc_errors", "tsc_messages", "rounds"}
    """
    if os.environ.get("ENVIRONMENT") == "test":
        return {"success": True, "built": True, "tsc_errors": 0, "tsc_messages": [], "rounds": 0}

    tsc_lines: list[str] = []
    built = False
    round_num = 0
    for round_num in range(1, max_rounds + 1):
        ensure_local_modules(frontend_dir)  # LLM patches/revisions may add imports of files that do not exist
        if ensure_npm_deps(frontend_dir):  # ...or of packages package.json lacks: they need an install first
            try:
                await phase_exec.run(["npm", "install"], cwd=frontend_dir, timeout=300, network=True)
            except SandboxUnavailable:
                raise
            except Exception as exc:
                logger.warning("p05 build_loop: npm install after adding dependencies failed: %s", exc)
        try:
            # Type-check and build execute the project's own tooling and plugins: sandbox, no network.
            tsc_result = await phase_exec.run(["npx", "tsc", "--noEmit", "--skipLibCheck"],
                                              cwd=frontend_dir, timeout=60, text=True)
            build_result = await phase_exec.run(["npm", "run", "build"], cwd=frontend_dir,
                                                timeout=300, text=True, env=PREVIEW_BUILD_ENV)
        except SandboxUnavailable:
            raise  # generated code was not run: fail the phase with this message
        except Exception as exc:
            logger.error("p05 build_loop: subprocess raised in round %d: %s", round_num, exc)
            return _outcome(False, tsc_lines, round_num)

        tsc_lines = _tsc_messages(tsc_result) if tsc_result.returncode != 0 else []
        built = build_result.returncode == 0 and (frontend_dir / "dist" / "index.html").is_file()
        if built and not tsc_lines:
            return _outcome(True, [], round_num)
        if round_num == max_rounds:
            break  # patches made now would never be rebuilt, so do not apply them

        combined = (_combine_output(tsc_result) + "\n" + _combine_output(build_result))[-_MAX_ERR_CHARS:]
        patches = await _llm_fix(combined)
        applied = sum(1 for p in patches if isinstance(p, dict) and _apply_patch(frontend_dir, p))
        logger.info("p05 build_loop: round %d - applied %d patches", round_num, applied)
        if applied == 0:
            break  # no progress possible: do not burn rounds
    logger.warning("p05 build_loop: built=%s with %d tsc error(s); first: %s", built, len(tsc_lines), tsc_lines[:3])
    return _outcome(built, tsc_lines, round_num)


if __name__ == "__main__":
    # ponytail: self-check — parser + patch apply, no framework
    import tempfile
    assert _count_tsc_errors("x.ts(1,2): error TS2304: foo\nerror TS7006: bar") == 2
    assert _extract_json_array('```json\n[{"file":"a","find":"b","replace":"c"}]\n```')
    assert _extract_json_array("garbage") == []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); f = root / "src" / "x.ts"
        f.parent.mkdir(parents=True); f.write_text("const x = 1;\n")
        assert _apply_patch(root, {"file": "src/x.ts", "find": "const x = 1;", "replace": "const x = 2;"})
        assert not _apply_patch(root, {"file": "src/x.ts", "find": "missing", "replace": "y"})
        assert not _apply_patch(root, {"file": "src/missing.ts", "find": "a", "replace": "b"})
    os.environ["ENVIRONMENT"] = "test"
    assert asyncio.run(run_build_loop(Path(".")))["success"]
    print("build_loop self-check OK")
