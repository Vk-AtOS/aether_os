"""One way for every stage to say why a sub-phase failed (KAN-249), and how to tell two failures apart (KAN-257).

Runs e53e5f12 and af268b8e (28 Nov 2026): s03 reported "backend_output_path is missing" while the real cause was the p04a
pre-generation validator rejecting the spec, and s04 recorded "sub-step reported failure" while the real tsc errors sat in
p05's metadata. A stage failure reason must carry the sub-phase's own error, never a generic or guessed one.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, List

# Metadata keys sub-phases use for their own error text, most specific first.
_CAUSE_KEYS = ("error", "pre_gen_errors", "validation_errors", "build_errors", "tsc_messages", "blocking_findings",
               "errors")
_MAX_CAUSES = 3
_MAX_CHARS = 300

# Text that names no cause: two attempts that both say this are not proven identical.
_GENERIC = re.compile(r"sub-step reported failure|reported success=false|returned success=false|"
                      r"no failure detail was recorded|failed or did not run|stage failed$", re.I)
# Volatile parts of an error message that differ between otherwise identical attempts.
_VOLATILE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|0x[0-9a-f]+|"
                       r"\d{4}-\d\d-\d\d[t ]\d\d:\d\d:\d\d[\d.:z+-]*|/(?:private/)?(?:var|tmp)/[^\s'\"]*|\b[0-9a-f]{12,}\b",
                       re.I)


def _as_texts(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in _as_texts(v)]
    return [" ".join(str(value).split())[:_MAX_CHARS]]


def sub_phase_causes(result: Any, limit: int = _MAX_CAUSES) -> List[str]:
    """The sub-phase's own error text: its issues, then the error keys of its metadata. At most `limit`, no duplicates."""
    texts = _as_texts(getattr(result, "issues", None))
    meta = getattr(result, "metadata", None) or {}
    for key in _CAUSE_KEYS:
        texts.extend(_as_texts(meta.get(key)))
    seen: List[str] = []
    for t in texts:
        if t not in seen:
            seen.append(t)
    return seen[:limit]


def failure_issues(stage: str, sub_phase: str, result: Any, limit: int = _MAX_CAUSES) -> List[str]:
    """Issue lines for a failed sub-phase: "<stage>: <sub_phase> failed: <its own error>".

    When the sub-phase recorded nothing, say so plainly instead of guessing a cause.
    """
    causes = sub_phase_causes(result, limit)
    if not causes:
        return [f"{stage}: {sub_phase} failed and recorded no error text (success=False)"]
    return [f"{stage}: {sub_phase} failed: {c}" for c in causes]


def exception_issue(stage: str, sub_phase: str, exc: BaseException) -> str:
    """Issue line for a sub-phase that raised: the exception type and message, never just 'failed'."""
    msg = " ".join(str(exc).split())[:_MAX_CHARS * 2]
    return f"{stage}: {sub_phase} raised {type(exc).__name__}: {msg}" if msg else f"{stage}: {sub_phase} raised {type(exc).__name__}"


def normalise_failure(issues: Iterable[str]) -> str:
    """Error text with run ids, timestamps, addresses and temp paths removed, so repeats compare equal."""
    text = "\n".join(sorted(" ".join(str(i).split()).lower() for i in issues if i))
    return _VOLATILE.sub("#", text)


def is_generic_failure(issues: Iterable[str]) -> bool:
    """True when the issue text names no real cause (empty, or only placeholders like 'sub-step reported failure')."""
    texts = [str(i) for i in issues if i]
    return not texts or all(_GENERIC.search(t) for t in texts)


def failure_fingerprint(issues: Iterable[str]) -> str:
    """Hash of the normalised error text; the same value twice means the attempt failed the same way."""
    return hashlib.sha256(normalise_failure(issues).encode()).hexdigest()[:16]
