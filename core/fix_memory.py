"""Structured, org-scoped memory of runs (KAN-215): repair fixes keyed by a normalised error signature, and short
bounded summaries of past runs' entities and patterns for prompts.

Same error class (missing UI primitive, case-mismatched import) used to cost a model call on every run. A fix that
worked is stored as {signature, file_kind, patches}; the next run looks it up by key first and tries it before any
model call. Interface (the caller supplies `validate`, so this module does not depend on any patch helper):
    lookup(org_id, signature) -> stored patches
    record(org_id, signature, file_kind, patches)
    apply_stored(org_id, signature, validate) -> patches that validated and were applied

Isolation: every query filters by org_id. Platform-level patterns are only GlobalPattern rows with org_id NULL
(domain / pattern name / type / rate: no customer content). Embedding search is deliberately not implemented: key
lookup (signature, domain, entity names) covers the observed error classes.
"""
from __future__ import annotations

import hashlib
import logging
import re
from contextlib import asynccontextmanager
from typing import Callable, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from aether_os.core.db import get_session_factory
from aether_os.core.models import GlobalPattern
from aether_os.core.models_memory import FixMemory, RunPatternMemory

logger = logging.getLogger(__name__)

MAX_FAILURES = 2            # a stored fix that fails twice is dropped
SUMMARY_MAX_TOKENS = 800    # bounded prompt memory; ~4 characters per token
_CHARS_PER_TOKEN = 4

# tsc: "src/pages/X.tsx(254,306): error TS2304: ..."; vite/esbuild: "/abs/src/pages/X.tsx:291:42: ERROR: ..."
_ERR_LINE = re.compile(
    r"^\s*(?P<file>\S+?\.(?:tsx|ts|jsx|js|css))(?:\((?P<l1>\d+),\d+\)|:(?P<l2>\d+):\d+):?\s*(?:error|ERROR)\b:?\s*(?P<msg>.+?)\s*$")
_QUOTED = re.compile(r"""'[^']*'|"[^"]*"|`[^`]*`""")
_PATH = re.compile(r"(?:[\w@.-]*/)+[\w@.-]+")
_NUM = re.compile(r"\b\d+\b")

# Memory poisoning guard (KAN-215): a stored patch is replayed into later builds with no model call, so only small,
# local, boring edits are stored. The replace text may not add a package import, a URL or dynamic code execution.
MAX_PATCH_CHARS = 400
LINE_SLACK = 3
_FORBIDDEN_REPLACE = re.compile(
    r"""https?://|\beval\b|\bFunction\s*\(|dangerouslySetInnerHTML|<\s*script|\brequire\s*\(|\bimport\s*\("""
    r"""|\bimport\b[^;\n]*?\bfrom\s*['"][^./'"][^'"]*['"]|\bimport\s*['"][^./'"]""", re.I)


def is_safe_patch(patch: dict) -> bool:
    """Small find/replace whose replace text passes the denylist (also re-checked on replay, for older rows)."""
    find, rep = patch.get("find"), patch.get("replace")
    return (isinstance(find, str) and isinstance(rep, str) and bool(find) and len(find) <= MAX_PATCH_CHARS
            and len(rep) <= MAX_PATCH_CHARS and not _FORBIDDEN_REPLACE.search(rep))


def patch_targets_error(patch: dict, err: dict, source: str) -> bool:
    """The patch edits the erroring file, within LINE_SLACK lines of the error line, and is safe."""
    if not is_safe_patch(patch) or not err.get("file") or not str(patch.get("file", "")).endswith(err["file"]):
        return False
    idx = source.find(patch["find"])
    if idx < 0 or not err.get("line"):
        return False
    first = source.count("\n", 0, idx) + 1
    last = first + patch["find"].count("\n")
    return first - LINE_SLACK <= err["line"] <= last + LINE_SLACK


def normalise_error(message: str) -> str:
    """Error text with identifiers, paths and numbers replaced by placeholders (the TS code stays)."""
    text = _QUOTED.sub("<id>", message)
    text = _PATH.sub("<path>", text)
    text = _NUM.sub("<n>", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def signature_of(message: str) -> str:
    return hashlib.sha256(normalise_error(message).encode()).hexdigest()[:40]


def file_kind_of(path: str) -> str:
    """e.g. 'tsx:pages' for src/pages/X.tsx: the kind of file the fix applies to, never its name."""
    parts = path.replace("\\", "/").split("/")
    ext = parts[-1].rsplit(".", 1)[-1] if "." in parts[-1] else ""
    return f"{ext}:{parts[-2]}" if len(parts) > 1 else ext


def parse_errors(output: str, limit: int = 10) -> list[dict[str, str]]:
    """[{signature, file, file_kind, line}] for the located errors of a tsc / vite output (first `limit`, one per signature+file)."""
    seen: set[tuple[str, str]] = set()
    found: list[dict[str, str]] = []
    for line in (output or "").splitlines():
        m = _ERR_LINE.match(line)
        if not m:
            continue
        sig, rel = signature_of(m["msg"]), m["file"]
        rel = rel[rel.rfind("src/"):] if "src/" in rel else rel
        if (sig, rel) in seen:
            continue
        seen.add((sig, rel))
        found.append({"signature": sig, "file": rel, "file_kind": file_kind_of(rel),
                      "line": int(m["l1"] or m["l2"] or 0)})
        if len(found) >= limit:
            break
    return found


@asynccontextmanager
async def _scope(session: Optional[AsyncSession]):
    """The caller's session, or a fresh one that is committed on success."""
    if session is not None:
        yield session
        await session.commit()
        return
    async with get_session_factory()() as own:
        yield own
        await own.commit()


async def _row(s: AsyncSession, org_id: str, signature: str) -> Optional[FixMemory]:
    return (await s.execute(select(FixMemory).where(FixMemory.org_id == org_id,
                                                    FixMemory.signature == signature))).scalar_one_or_none()


async def lookup(org_id: str, signature: str, session: Optional[AsyncSession] = None) -> list[dict]:
    """Stored patches for this org and signature (empty when unknown). Never reads another org's rows."""
    if not org_id:
        return []
    async with _scope(session) as s:
        row = await _row(s, org_id, signature)
        return list(row.patches) if row else []


async def record(org_id: str, signature: str, file_kind: str, patches: list[dict], run_id: Optional[str] = None,
                 user_id: str = "system", session: Optional[AsyncSession] = None) -> None:
    """Store (or refresh) a fix that worked, with its provenance (run_id, user_id). A refreshed fix starts with a
    clean failure count. Unsafe patches are never stored."""
    clean = [{k: p[k] for k in ("file", "find", "replace") if k in p}
             for p in patches if isinstance(p, dict) and is_safe_patch(p)]
    if not org_id or not clean:
        return
    async with _scope(session) as s:
        row = await _row(s, org_id, signature)
        if row:
            row.patches, row.file_kind, row.failures = clean, file_kind, 0
            row.run_id, row.user_id = run_id, user_id
        else:
            s.add(FixMemory(org_id=org_id, signature=signature, file_kind=file_kind, patches=clean,
                            run_id=run_id, user_id=user_id))


async def purge_run(org_id: str, run_id: str, session: Optional[AsyncSession] = None) -> int:
    """Delete every fix this org stored from `run_id` (audit / incident response). Returns the rows deleted."""
    async with _scope(session) as s:
        res = await s.execute(delete(FixMemory).where(FixMemory.org_id == org_id, FixMemory.run_id == run_id))
        return res.rowcount or 0


async def mark_hit(org_id: str, signature: str, session: Optional[AsyncSession] = None) -> None:
    async with _scope(session) as s:
        row = await _row(s, org_id, signature)
        if row:
            row.hits, row.failures = row.hits + 1, 0


async def mark_failure(org_id: str, signature: str, session: Optional[AsyncSession] = None) -> bool:
    """The stored fix was applied but the error is still there. True when it was dropped (failed twice)."""
    async with _scope(session) as s:
        row = await _row(s, org_id, signature)
        if not row:
            return False
        row.failures += 1
        if row.failures >= MAX_FAILURES:
            await s.execute(delete(FixMemory).where(FixMemory.org_id == org_id, FixMemory.id == row.id))
            return True
        return False


async def apply_stored(org_id: str, signature: str, validate: Callable[[dict], bool],
                       target_file: Optional[str] = None, session: Optional[AsyncSession] = None) -> list[dict]:
    """Try the stored patches; `validate(patch)` applies it and says whether it applies cleanly. Returns the applied.
    With `target_file` the stored path is ignored and the patch only ever touches the file of the current error."""
    stored = await lookup(org_id, signature, session)
    return [p for p in ({**q, "file": target_file} if target_file else q for q in stored)
            if is_safe_patch(p) and validate(p)]


async def record_run(org_id: str, run_id: str, domain: str, entities: Iterable[str], patterns: Iterable[str],
                     session: Optional[AsyncSession] = None) -> None:
    """Typed row of what a finished run chose. Idempotent per (org, run)."""
    async with _scope(session) as s:
        row = (await s.execute(select(RunPatternMemory).where(
            RunPatternMemory.org_id == org_id, RunPatternMemory.run_id == run_id))).scalar_one_or_none()
        ents, pats = sorted({str(e) for e in entities}), sorted({str(p) for p in patterns})
        if row:
            row.domain, row.entities, row.patterns = domain, ents, pats
        else:
            s.add(RunPatternMemory(org_id=org_id, run_id=run_id, domain=domain, entities=ents, patterns=pats))


async def prompt_summary(org_id: str, domain: str, entity_names: Iterable[str] = (),
                         max_tokens: int = SUMMARY_MAX_TOKENS, session: Optional[AsyncSession] = None) -> str:
    """Short, bounded memory for a prompt: this org's past runs in the domain (best entity overlap first) plus
    platform patterns (org_id NULL). Never whole past runs."""
    budget, wanted = max_tokens * _CHARS_PER_TOKEN, {e.lower() for e in entity_names}
    async with _scope(session) as s:
        runs = (await s.execute(select(RunPatternMemory).where(
            RunPatternMemory.org_id == org_id, RunPatternMemory.domain == domain)
            .order_by(RunPatternMemory.created_at.desc()).limit(20))).scalars().all()
        plat = (await s.execute(select(GlobalPattern).where(
            GlobalPattern.org_id.is_(None), GlobalPattern.domain == domain)
            .order_by(GlobalPattern.success_rate.desc()).limit(5))).scalars().all()
    runs = sorted(runs, key=lambda r: -len(wanted & {e.lower() for e in r.entities}))[:5]
    lines = [f"- past run ({domain}): entities {', '.join(r.entities[:12])}; patterns {', '.join(r.patterns[:8])}"
             for r in runs]
    lines += [f"- platform pattern: {p.pattern_name} ({p.pattern_type}, success {p.success_rate:.0%})" for p in plat]
    out, used = [], 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return "Memory from earlier runs:\n" + "\n".join(out) if out else ""
