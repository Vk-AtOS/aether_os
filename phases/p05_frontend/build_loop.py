"""P05 Frontend — Compile-error feedback loop.

Runs `tsc --noEmit` + `vite build` and feeds any errors back to the LLM for
targeted find/replace patches. Retries up to max_rounds before giving up.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from aether_os.core.run_context import ACTIVE_ORG_ID, ACTIVE_RUN_ID
from aether_os.core.sandbox import phase_exec
from aether_os.core.codegen.patching import (
    apply_patch_text, apply_verified, build_prompt, error_context, extract_json_array as _extract_json_array, request_patches, resolve_in_project,
)
from aether_os.core.sandbox.runner import SandboxUnavailable
from aether_os.phases.p05_frontend.fix_memory_hook import RoundMemory
from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules
from aether_os.phases.p05_frontend.npm_deps import ensure_npm_deps
from aether_os.phases.p05_frontend.npm_runner import PREVIEW_BUILD_ENV
from aether_os.prime.learning import loop as learning

logger = logging.getLogger(__name__)

_TS_ERROR_RE = re.compile(r"error TS\d+:")
_MAX_ERR_CHARS = 3000
MAX_TSC_MESSAGES = 10
def _count_tsc_errors(text: str) -> int:
    return len(_TS_ERROR_RE.findall(text or ""))


def _combine_output(result: subprocess.CompletedProcess) -> str:
    out = (result.stdout or "") + (result.stderr or "")
    return out[-_MAX_ERR_CHARS:]


def _error_context(frontend_dir: Path, error_output: str) -> str:
    return error_context(frontend_dir, error_output)


def _apply_patch(frontend_dir: Path, patch: dict) -> bool:
    """Apply one find/replace patch unverified (kept for callers/tests; the build loop uses apply_verified)."""
    target = resolve_in_project(frontend_dir, patch.get("file", ""))
    if target is None or not patch.get("find"):
        return False
    try:
        new, why = apply_patch_text(target.read_text(), patch["find"], patch.get("replace", ""))
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("p05 build_loop: read %s failed: %s", target, exc)
        return False
    if why:
        return False
    target.write_text(new)
    return True


async def _llm_fix(error_output: str, source: str = "") -> list[dict[str, Any]]:
    prompt = build_prompt("You are a TypeScript/React developer. The errors occurred during `tsc --noEmit` and/or "
                          "`vite build`.", error_output, source, example="src/pages/X.tsx")
    return await request_patches(prompt, "p05 build_loop")


def _may_patch(frontend_dir: Path):
    """Only the app's own sources and package.json: never configs, tests or anything outside the frontend."""
    root = frontend_dir.resolve()

    def allowed(target: Path) -> bool:
        rel = target.relative_to(root).parts
        return rel == ("package.json",) or (rel[0] == "src" and not any(t in ("tests", "__tests__") for t in rel))
    return allowed


_SYNTAX_TS = re.compile(r"error TS(?:1\d{3}|17\d{3}):")   # TS1xxx and TS17xxx (JSX): parse errors


def _syntax_errors(lines: list[str]) -> int:
    return sum(1 for ln in lines if _SYNTAX_TS.search(ln))


async def _tsc_not_worse(frontend_dir: Path, before: list[str]) -> bool:
    """True when the patches did not make `tsc --noEmit` (sandboxed, as in the loop) worse.

    Syntax errors decide first: while a file does not parse, tsc reports only that and stops, so fixing it lets tsc
    reach the type errors behind it and the total goes up. Counting the total rolled back the correct closing-tag
    fix on production acceptance run 16 (22 Nov 2026) and s04 failed; type errors alone do not fail the build.
    """
    res = await phase_exec.run(["npx", "tsc", "--noEmit", "--skipLibCheck"], cwd=frontend_dir, timeout=60, text=True)
    if res.returncode == 0:
        return True
    after = _tsc_messages(res)
    syn_before, syn_after = _syntax_errors(before), _syntax_errors(after)
    if syn_after != syn_before:
        return syn_after < syn_before
    return len(after) <= len(before)


def _tsc_messages(tsc_result: subprocess.CompletedProcess) -> list[str]:
    out = (tsc_result.stdout or "") + (tsc_result.stderr or "")
    lines = [ln.strip()[:300] for ln in out.splitlines() if "error TS" in ln]
    if not lines and tsc_result.returncode != 0:  # tsc died without TS diagnostics: still a type-check failure
        lines = [out.strip().splitlines()[-1][:300] if out.strip() else f"tsc exited {tsc_result.returncode}"]
    return lines


def _manifest_digest(frontend_dir) -> str:
    """sha256 of package.json, or "" when it is missing or unreadable."""
    try:
        return hashlib.sha256((frontend_dir / "package.json").read_bytes()).hexdigest()
    except OSError as exc:
        logger.warning("p05 build_loop: cannot read package.json: %s", exc)
        return ""


def _build_error_lines(output: str, limit: int = 1500) -> str:
    """The lines that say WHY a bundle failed. The output's tail is mostly a stack trace: on production acceptance run 7
    (22 Nov 2026) the logged last 1500 characters were all `at ...` frames, and the message itself was cut off."""
    lines = [ln for ln in output.splitlines() if ln.strip() and not ln.lstrip().startswith("at ")]
    keep = [ln for ln in lines if any(k in ln.lower() for k in ("error", "could not", "failed", "cannot", "not exported",
                                                                 "unresolved", "resolve"))] or lines[-20:]
    return "\n".join(keep)[:limit]


def _outcome(built: bool, tsc_lines: list[str], rounds: int, build_errors: str = "") -> dict:
    # build_errors: why the bundle failed, so the stage gate can name the files (KAN-210)
    # success needs a clean type-check as well as a bundle: `vite build` does not type-check, so a build that only
    # bundled shipped ~10 type errors in every product (KAN-251). `built` stays the bundle result.
    out = {"success": built and not tsc_lines, "built": built, "tsc_errors": len(tsc_lines), "tsc_messages": tsc_lines[:MAX_TSC_MESSAGES],
           "tsc_all": tsc_lines, "rounds": rounds}   # tsc_all: the crash gate needs every error, not the first few
    return {**out, "build_errors": build_errors} if build_errors else out


def result_summary(loop: dict) -> tuple[dict, list[str]]:
    """(metadata, issues) the phase reports for a build_loop outcome: the tsc count and first messages are visible in
    the run result, and a bundled app with leftover type errors carries a warning instead of a failure."""
    n = int(loop.get("tsc_errors", 0))
    meta = {"build_ok": bool(loop.get("built", loop.get("success"))), "tsc_errors": n, "type_check_ok": n == 0,
            "tsc_messages": list(loop.get("tsc_messages", [])),
            "build_errors": str(loop.get("build_errors", ""))}
    issues = []
    if n and meta["build_ok"]:
        issues.append(f"p05 error: vite build succeeded but {n} TypeScript error(s) remain, so the build fails. First: "
                      + " | ".join(meta["tsc_messages"][:3]))
    return meta, issues


async def run_build_loop(frontend_dir: Path, max_rounds: int = 3, org_id: str | None = None) -> dict:
    """tsc --noEmit + vite build -> parse errors -> LLM fix per round -> max_rounds.

    Policy (KAN-251): the phase SUCCEEDS when `vite build` exits 0, produced dist/index.html AND `tsc --noEmit` is
    clean. `vite build` does not type-check, so type errors used to ship. While errors remain the loop asks the model to
    fix them; what is left is returned as a count plus the first MAX_TSC_MESSAGES messages and fails the build.

    Returns: {"success", "built", "tsc_errors", "tsc_messages", "rounds"}
    """
    if os.environ.get("ENVIRONMENT") == "test":
        return {"success": True, "built": True, "tsc_errors": 0, "tsc_messages": [], "rounds": 0}
    org_id = org_id or ACTIVE_ORG_ID.get()
    result = await _build_rounds(frontend_dir, max_rounds, org_id)
    # KAN-229: the run's first build is the first-pass trend, and settles the golden examples its prompts used.
    await learning.record_build(org_id, ACTIVE_RUN_ID.get(), result["built"],
                                result["built"] and not result["tsc_errors"] and result["rounds"] == 1,
                                result["rounds"])
    return result


async def _build_rounds(frontend_dir: Path, max_rounds: int, org_id: str | None) -> dict:
    memory = RoundMemory(org_id or ACTIVE_ORG_ID.get(), frontend_dir, _apply_patch)  # KAN-215: org-scoped fix memory
    tsc_lines: list[str] = []
    built = False
    build_errors = ""
    round_num = 0
    installed_manifest = _manifest_digest(frontend_dir)   # what node_modules was installed from before the loop
    for round_num in range(1, max_rounds + 1):
        ensure_local_modules(frontend_dir)  # LLM patches/revisions may add imports of files that do not exist
        added = ensure_npm_deps(frontend_dir)  # ...or of packages package.json lacks: they need an install first
        # A model patch can also edit package.json itself. Without a reinstall the next build cannot resolve the new
        # import, fails, and the project only builds later when another step reinstalls (production run 7, 22 Nov 2026).
        if added or _manifest_digest(frontend_dir) != installed_manifest:
            try:
                await phase_exec.run(["npm", "install"], cwd=frontend_dir, timeout=300, network=True)
            except SandboxUnavailable:
                raise
            except Exception as exc:
                logger.warning("p05 build_loop: npm install after adding dependencies failed: %s", exc)
            installed_manifest = _manifest_digest(frontend_dir)
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
        build_errors = "" if built else _build_error_lines(_combine_output(build_result))
        if not built:
            # Without this the only trace of a failed bundle was the tsc count, so "built=False" on a real run could
            # not be diagnosed afterwards (production acceptance run 4, 22 Nov 2026).
            logger.warning("p05 build_loop: round %d build failed (exit %s, dist/index.html %s): %s", round_num,
                           build_result.returncode, (frontend_dir / "dist" / "index.html").is_file(),
                           _build_error_lines(_combine_output(build_result)))
        full_output = _combine_output(tsc_result) + "\n" + _combine_output(build_result)
        await memory.settle(full_output)  # store / confirm the fixes the last round applied
        if built and not tsc_lines:
            return _outcome(True, [], round_num)
        if round_num == max_rounds:
            break  # patches made now would never be rebuilt, so do not apply them

        if await memory.try_known(full_output):
            continue  # a stored fix was applied (no model call): rebuild to validate it
        combined = full_output[-_MAX_ERR_CHARS:]
        patches = await _llm_fix(combined, _error_context(frontend_dir, combined))
        memory.screen_model_patches(full_output, patches)  # before applying: needs the unpatched source
        report = await apply_verified(frontend_dir, patches, _may_patch(frontend_dir), "p05 build_loop",
                                      lambda: _tsc_not_worse(frontend_dir, tsc_lines))
        report.log("p05 build_loop", round_num)
        memory.remember_model_patches(report.applied_patches)   # KAN-215: settle() keeps those that fixed the error
        if report.applied == 0:
            break  # no progress possible: do not burn rounds
    logger.warning("p05 build_loop: built=%s with %d tsc error(s); first: %s", built, len(tsc_lines), tsc_lines[:3])
    return _outcome(built, tsc_lines, round_num, build_errors)


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
