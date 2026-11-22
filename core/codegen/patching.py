"""Repair by small verified patches (KAN-212).

Whole-file rewrites by a model were slow, truncated mid-call and dropped code (production acceptance runs 12-13,
22 Nov 2026). Every fixer instead shows the model numbered source around each error, asks for a JSON list of
`{file, find, replace}`, applies a patch only when `find` occurs exactly once, validates the touched files and rolls a
file back when validation fails. Whole-file rewrites remain only for tiny files and only behind `reject_rewrite`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from aether_os.core.llm.json_enforcer import extract_first_json

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 6000
CONTEXT_RADIUS = 12
MAX_REWRITE_CHARS = 3000   # a whole-file rewrite is only allowed below this size
_SKIP_PARTS = ("node_modules", ".git", "__pycache__")

# tsc: "src/pages/X.tsx(254,306): error"; vite/esbuild: "/abs/.../src/pages/X.tsx:291:42: ERROR"
_LOC_RE = re.compile(r"((?:[\w@.-]+/)*[\w@.-]+\.(?:tsx|ts|jsx|js|css))(?:\((\d+),\d+\)|:(\d+):\d+)")
_PY_LOC_RE = re.compile(r'File "([^"]+\.py)", line (\d+)')

PATCH_PROMPT = (
    "{role} Fix the errors below. List the exact fixes as a JSON array of "
    '{{"file": "{example}", "find": "old text", "replace": "new text"}} '
    "objects. `find` must be copied exactly from the source below (without the line-number prefix), must occur "
    "exactly once in its file, and should be short and unique. Do not rewrite whole files. Return ONLY the JSON "
    "array, no prose.{extra}\n\nErrors:\n{errors}\n\nSource around the errors:\n{source}"
)


@dataclass
class PatchReport:
    proposed: int = 0
    applied: int = 0
    rolled_back: int = 0
    reasons: list[str] = field(default_factory=list)
    touched: list[Path] = field(default_factory=list)   # files that still carry an applied patch

    def log(self, tag: str, round_num: int) -> None:
        """One line per repair round: proposed, applied, rolled back (and why when nothing applied)."""
        logger.info("%s: round %d - proposed %d, applied %d, rolled back %d%s", tag, round_num, self.proposed,
                    self.applied, self.rolled_back,
                    "" if self.applied else f" ({'; '.join(self.reasons[:3]) or 'no patches proposed'})")


def extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Pull first JSON array out of an LLM response (may be fenced or prefaced)."""
    if not raw:
        return []
    try:
        return extract_first_json(raw, expect=list)
    except ValueError as exc:
        logger.warning("patching: JSON parse failed: %s", exc)
        return []


def resolve_in_project(root: Path, path_str: str) -> Optional[Path]:
    """The file a model-supplied path names, or None when it leaves the project (`../x`, absolute, symlink),
    is under node_modules/.git, or is not an existing file."""
    if not path_str:
        return None
    base = root.resolve()
    target = (root / path_str).resolve()
    if not target.is_relative_to(base) or any(p in _SKIP_PARTS for p in target.relative_to(base).parts):
        logger.warning("patching: patch path %r rejected (outside the project)", path_str)
        return None
    return target if target.is_file() else None


def error_context(root: Path, error_output: str, max_files: int = 3, radius: int = CONTEXT_RADIUS) -> str:
    """Numbered source lines around the first error of each file (at most `max_files` files).

    Understands tsc/vite locations and Python tracebacks. Without the source the model had to guess the exact text to
    replace: production acceptance run 12 (22 Nov 2026) failed s04 three times with "applied 0 patches" on a broken
    JSX line it had never been shown.
    """
    base = root.resolve()
    hits: list[tuple[str, int]] = []
    for m in _LOC_RE.finditer(error_output or ""):
        rel = m.group(1)
        hits.append((rel[rel.index("src/"):] if "src/" in rel else rel, int(m.group(2) or m.group(3))))
    for m in _PY_LOC_RE.finditer(error_output or ""):
        p = m.group(1)
        if p.startswith("/"):
            try:
                p = str(Path(p).resolve().relative_to(base))
            except ValueError:
                continue   # stdlib / site-packages / host path
        hits.append((p, int(m.group(2))))
    seen: dict[Path, int] = {}
    for rel, line in hits:
        target = (root / rel).resolve()
        if target in seen or not target.is_relative_to(base) or not target.is_file():
            continue
        seen[target] = line
        if len(seen) == max_files:
            break
    parts = []
    for target, line in seen.items():
        try:
            lines = target.read_text().splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("patching: cannot read %s for error context: %s", target, exc)
            continue
        lo, hi = max(1, line - radius), min(len(lines), line + radius)
        body = "\n".join(f"{n}| {lines[n - 1][:400]}" for n in range(lo, hi + 1))
        parts.append(f"--- {target.relative_to(base)} (lines {lo}-{hi})\n{body}")
    return "\n".join(parts)[:MAX_SOURCE_CHARS] or "(no source located)"


def build_prompt(role: str, errors: str, source: str, example: str = "src/x.py", extra: str = "") -> str:
    return PATCH_PROMPT.format(role=role, errors=errors, source=source or "(no source located)", example=example,
                               extra=("\n" + extra) if extra else "")


async def request_patches(prompt: str, tag: str, timeout: float = 60.0) -> list[dict[str, Any]]:
    """Ask the model for a patch list. Never raises: a failed call is an empty list."""
    from aether_os.core.llm.client import get_llm_client   # lazy: the client pulls in the provider stack
    try:
        raw = await asyncio.wait_for(
            # Reasoning models spend part of max_tokens thinking; 2000 truncated replies on production runs.
            get_llm_client().call(prompt, task_type="code_generation", max_tokens=4000), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s: LLM fix call timed out", tag)
        return []
    except Exception as exc:
        logger.warning("%s: LLM fix call failed: %s", tag, exc)
        return []
    return extract_json_array(raw)


def validate_python(path: Path, text: str) -> str:
    """"" when `text` compiles, else the reason. compile() (not ast.parse) also catches duplicate keyword arguments."""
    try:
        compile(text, path.name, "exec")
    except (SyntaxError, ValueError) as exc:
        return f"syntax error line {getattr(exc, 'lineno', '?')}: {getattr(exc, 'msg', exc)}"
    return ""


def apply_patch_text(text: str, find: str, replace: str) -> tuple[str, str]:
    """(new_text, "") or (text, reason): `find` must occur exactly once."""
    n = text.count(find)
    if n != 1:
        return text, "find not found" if n == 0 else f"find is ambiguous ({n} matches)"
    return text.replace(find, replace, 1), ""


def _valid_patch(p: Any) -> bool:
    return isinstance(p, dict) and all(isinstance(p.get(k), str) for k in ("file", "find")) \
        and isinstance(p.get("replace", ""), str) and bool(p["file"]) and bool(p["find"])


async def apply_verified(
    root: Path,
    patches: list,
    tag: str = "patching",
    ts_check: Optional[Callable[[], Awaitable[bool]]] = None,
) -> PatchReport:
    """Apply `patches` under `root`; keep only the ones that validate.

    .py files must compile (checked per file). For TS/JS files `ts_check()` runs once after all of them were written
    (the sandboxed `tsc --noEmit`) and returns False when the patches made things worse; then every TS/JS file of
    this round is restored. Patches to one file are applied in order against the evolving text.
    """
    rep = PatchReport(proposed=len(patches))
    originals: dict[Path, str] = {}
    current: dict[Path, str] = {}
    counts: dict[Path, int] = {}
    for p in patches:
        if not _valid_patch(p):
            rep.reasons.append("malformed patch")
            continue
        target = resolve_in_project(root, p["file"])
        if target is None:
            rep.reasons.append(f"{p['file']}: no such file in the project")
            continue
        try:
            text = current[target] if target in current else target.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("%s: read %s failed: %s", tag, target, exc)
            rep.reasons.append(f"{p['file']}: unreadable")
            continue
        new, why = apply_patch_text(text, p["find"], p.get("replace", ""))
        if why:
            rep.reasons.append(f"{p['file']}: {why}")
            continue
        originals.setdefault(target, text)
        current[target] = new
        counts[target] = counts.get(target, 0) + 1

    ts_files = []
    for target, new in current.items():
        if target.suffix == ".py":
            why = validate_python(target, new)
            if why:
                rep.rolled_back += counts[target]
                rep.reasons.append(f"{target.name}: rolled back, {why}")
                continue
        elif ts_check is not None and target.suffix in (".ts", ".tsx", ".js", ".jsx"):
            ts_files.append(target)
        _write(target, new, rep, counts[target])
    if ts_files and ts_check is not None:
        try:
            ok = await ts_check()
        except Exception as exc:
            if type(exc).__name__ == "SandboxUnavailable":
                raise   # generated code was not run: the phase must fail with that message
            logger.warning("%s: patch validation raised, rolling back: %s", tag, exc)
            ok = False
        if not ok:
            for target in ts_files:
                if target in rep.touched:
                    target.write_text(originals[target])
                    rep.touched.remove(target)
                    rep.applied -= counts[target]
                    rep.rolled_back += counts[target]
            rep.reasons.append("tsc reported more errors after the patches: rolled back")
    return rep


def _write(target: Path, new: str, rep: PatchReport, n: int) -> None:
    try:
        target.write_text(new)
    except OSError as exc:
        logger.warning("patching: write %s failed: %s", target, exc)
        rep.reasons.append(f"{target.name}: write failed")
        return
    rep.applied += n
    rep.touched.append(target)


def reject_rewrite(fixed: str, original: str, path: Path) -> str:
    """Why a model's whole-file rewrite must not be written, or "" when it may.

    Guards (the same ones #59 put on crud.py): it compiles, it keeps every exported name, it is not under half the
    size. Only files below MAX_REWRITE_CHARS may be rewritten at all. A reply cut off mid-call (acceptance run 13,
    `model_dump(exclude_u`) fails the compile guard.
    """
    if len(original) >= MAX_REWRITE_CHARS:
        return f"file too large for a whole-file rewrite ({len(original)} chars)"
    if path.suffix == ".py":
        why = validate_python(path, fixed)
        if why:
            return why
        names = re.findall(r"^(?:async\s+def|def|class)\s+(\w+)|^(\w+)\s*=", original, re.MULTILINE)
        for name in {a or b for a, b in names}:
            if not re.search(rf"\b{re.escape(name)}\b", fixed):
                return f"drops {name}"
    if len(fixed) < 0.5 * len(original):
        return f"lost most of the file ({len(fixed)} of {len(original)} chars)"
    return ""
