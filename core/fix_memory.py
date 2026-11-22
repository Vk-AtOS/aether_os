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
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
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

# Memory poisoning guard (KAN-215). A stored patch is replayed into later builds with no model call, so only two
# narrow EDIT SHAPES (A import-path case fix, C missing closing tags) are storable (see is_safe_patch); everything
# else is refused. Code cannot be filtered with regexes or denylists alone (comments split tokens, strings concatenate into URLs, number grammar swallows names).
MAX_PATCH_CHARS = 400
LINE_SLACK = 3
_TOKEN = re.compile(
    r"""(?P<ws>\s+)|(?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))|(?P<tpl>`(?:\\.|[^`\\])*(?:`|\Z))"""
    r"""|(?P<str>'(?:\\.|[^'\\\n])*(?:'|(?=\n)|\Z)|"(?:\\.|[^"\\\n])*(?:"|(?=\n)|\Z))"""
    r"""|(?P<num>\d+(?:\.\d+)?)|(?P<id>[A-Za-z_$][A-Za-z0-9_$]*)"""
    r"""|(?P<punct>\.\.\.|\?\.|\*\*|===|!==|=>|--|\+\+|.)""", re.S)
_ESCAPE = re.compile(r"\\[ux]", re.I)
_SPEC_PATH = re.compile(r"(?:\./|\.\./)[\w./@-]*")
# Identifiers a patch may never introduce (also as a rename target or JSX tag).
_DENIED_IDENTIFIERS = frozenset(
    "eval Function constructor prototype __proto__ Reflect Proxy window globalThis self top parent frames document "
    "location cookie localStorage sessionStorage indexedDB fetch XMLHttpRequest WebSocket EventSource navigator "
    "postMessage importScripts require import export from setTimeout setInterval innerHTML outerHTML "
    "insertAdjacentHTML dangerouslySetInnerHTML srcdoc atob btoa open script iframe String fromCharCode "
    "decodeURIComponent unescape Image opener Worker SharedWorker Blob URL createObjectURL".split())
_SRC_EXTS = ("", ".ts", ".tsx", ".js", ".jsx")
Token = tuple[str, str]


def tokenize(src: str) -> list[Token]:
    """Tiny JS/TS tokenizer: (kind, text) with kind in id, num, str, tpl, comment, punct. Whitespace is dropped."""
    return [(m.lastgroup, m.group()) for m in _TOKEN.finditer(src) if m.lastgroup != "ws"]


def _relative_spec(tok: Token) -> bool:
    """A terminated string token holding a relative path ('./x', '../x'): no ':', no '//', plain path characters."""
    text = tok[1]
    return (tok[0] == "str" and len(text) > 1 and text[0] == text[-1] and bool(_SPEC_PATH.fullmatch(text[1:-1]))
            and "//" not in text[1:-1])


def _ok_id(tok: Token) -> bool:
    return tok[0] == "id" and tok[1] not in _DENIED_IDENTIFIERS


def _shape_import_path(tf: list[Token], tr: list[Token]) -> bool:
    """A) exactly one string token changes: the specifier of an import/export statement, and only its LETTER CASE
    (same length, same quotes, relative path). Replay additionally resolves it (import_target_ok)."""
    if len(tf) != len(tr):
        return False
    diff = [i for i in range(len(tf)) if tf[i] != tr[i]]
    if len(diff) != 1:
        return False
    i = diff[0]
    old, new = tf[i][1], tr[i][1]
    return (i > 0 and tf[i - 1] == ("id", "from") and _relative_spec(tf[i]) and _relative_spec(tr[i])
            and len(old) == len(new) and old.lower() == new.lower())


def _shape_closing_tags(find: str, rep: str, tf: list[Token]) -> bool:
    """C) raw text: replace == find + suffix, and the suffix without whitespace is only `</Name>` closing tags for
    names already opened in find."""
    if not rep.startswith(find) or len(rep) == len(find):
        return False
    compact = re.sub(r"\s+", "", rep[len(find):])
    if not re.fullmatch(r"(?:</[A-Za-z_$][A-Za-z0-9_$]*>)+", compact):
        return False
    opened = {tf[i][1] for i in range(1, len(tf)) if tf[i][0] == "id" and tf[i - 1] == ("punct", "<")}
    names = re.findall(r"</([A-Za-z_$][A-Za-z0-9_$]*)>", compact)
    return all(n in opened and n not in _DENIED_IDENTIFIERS for n in names)


def import_target_ok(frontend_dir: Path, file: str, patch: dict) -> bool:
    """Every `from '<relative>'` specifier of replace must resolve, from the patched file's directory, to an existing
    file (or index file) INSIDE <frontend_dir>/src, with the exact letter case on disk."""
    toks = tokenize(patch.get("replace", ""))
    root = (frontend_dir / "src").resolve()
    base = (frontend_dir / file).resolve().parent
    for i, (kind, text) in enumerate(toks):
        if kind != "str" or i == 0 or toks[i - 1] != ("id", "from"):
            continue
        target = (base / text[1:-1]).resolve()
        if not target.is_relative_to(root):
            return False
        cands = [target.parent / (target.name + e) for e in _SRC_EXTS] + \
                [target / ("index" + e) for e in _SRC_EXTS[1:]]
        if not any(c.is_file() and c.name in os.listdir(c.parent) for c in cands if c.parent.is_dir()):
            return False
    return True


def is_safe_patch(patch: dict) -> bool:
    """Storable / replayable only if the edit is exactly one of two shapes: A case-only import-path fix, C missing
    JSX closing tags (identifier renames and added named imports are NOT allowed). Comments, template literals,
    backslashes and escapes are refused outright; numbers, other strings and punctuation can never change.
    Also re-checked on replay (older rows)."""
    find, rep = patch.get("find"), patch.get("replace")
    if not (isinstance(find, str) and isinstance(rep, str) and find and len(find) <= MAX_PATCH_CHARS
            and len(rep) <= MAX_PATCH_CHARS) or _ESCAPE.search(find + rep) or "\\" in find + rep:
        return False
    tf, tr = tokenize(find), tokenize(rep)
    if any(k in ("comment", "tpl") for k, _ in tf + tr) or tf == tr:
        return False
    return (_shape_import_path(tf, tr) or _shape_closing_tags(find, rep, tf))


def patch_targets_error(patch: dict, err: dict, source: str, frontend_dir: Optional[Path] = None) -> bool:
    """The patch edits the erroring file, within LINE_SLACK lines of the error line, and is safe; with `frontend_dir`
    its import specifiers must also resolve inside src/ (import_target_ok)."""
    if not is_safe_patch(patch) or not err.get("file") or not str(patch.get("file", "")).endswith(err["file"]):
        return False
    idx = source.find(patch["find"])
    if idx < 0 or not err.get("line"):
        return False
    first = source.count("\n", 0, idx) + 1
    last = first + patch["find"].count("\n")
    if not first - LINE_SLACK <= err["line"] <= last + LINE_SLACK:
        return False
    return frontend_dir is None or import_target_ok(frontend_dir, err["file"], patch)


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
                       target_file: Optional[str] = None, guard: Optional[Callable[[dict], bool]] = None,
                       session: Optional[AsyncSession] = None) -> list[dict]:
    """Try the stored patches; `validate(patch)` applies it and says whether it applies cleanly. Returns the applied.
    With `target_file` the stored path is ignored and the patch only ever touches the file of the current error.
    `guard(patch)` runs before validate (the caller checks the patch against the CURRENT error line and source)."""
    stored = await lookup(org_id, signature, session)
    return [p for p in ({**q, "file": target_file} if target_file else q for q in stored)
            if is_safe_patch(p) and (guard is None or guard(p)) and validate(p)]


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
