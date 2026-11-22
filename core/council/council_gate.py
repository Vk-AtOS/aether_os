"""
AetherOS — gate in front of the BackendAuditCouncil (KAN-213).

Root cause it fixes: the council ran on every s03_backend retry, re-reviewing the same
files (run 13: 5 times), and a 0.00 "score" that really meant "no reviewer answered"
(run 16) was read as a verdict and re-ran the whole stage twice.

Rules:
  1. The council only runs after the cheap tool check (every .py file compiles) passed.
  2. The verdict is cached per run by a content hash of the reviewed text.
  3. A report with no scored review is "review unavailable", never a failing verdict.
  4. Council calls are counted and logged per run.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

REVIEWED = "reviewed"
CACHED = "cached"
UNAVAILABLE = "unavailable"
SKIPPED_CHECKS = "skipped_checks_failed"

_verdicts: Dict[Tuple[str, str], Any] = {}
_calls: Dict[str, int] = {}


def content_hash(files: Mapping[str, str]) -> str:
    """Stable hash of (name, text) pairs, order independent."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(files[name].encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def cheap_check_errors(files: Mapping[str, str]) -> List[str]:
    """The cheap tool check for backend files: every .py must compile."""
    errors: List[str] = []
    for name, text in files.items():
        if not name.endswith(".py"):
            continue
        try:
            compile(text, name, "exec")
        except SyntaxError as e:
            errors.append(f"{name}:{e.lineno}: {e.msg}")
    return errors


def review_available(report: Any) -> bool:
    """True only when at least one reviewer returned a usable (non-zero) score.

    CouncilReport.average_score is 0.0 when no model answered or the input was
    empty; that is "no review", not "the code scored 0".
    """
    reviews = getattr(report, "reviews", None) or []
    return any(getattr(r, "score", 0) > 0 for r in reviews)


def calls_for(run_id: str) -> int:
    return _calls.get(run_id, 0)


async def gated_review(
    run_id: str,
    files: Mapping[str, str],
    run_council_fn: Callable[[], Awaitable[Any]],
    label: str = "BackendAuditCouncil",
) -> Tuple[Optional[Any], str]:
    """Return (report or None, status). Only calls run_council_fn when it must."""
    if not any(t.strip() for t in files.values()):
        logger.warning("[%s] run %s: nothing to review — review unavailable", label, run_id)
        return None, UNAVAILABLE

    errors = cheap_check_errors(files)
    if errors:
        logger.info(
            "[%s] run %s: skipped, cheap checks failed (%d): %s",
            label, run_id, len(errors), "; ".join(errors[:3]),
        )
        return None, SKIPPED_CHECKS

    key = (run_id, content_hash(files))
    if key in _verdicts:
        logger.info(
            "[%s] run %s: files unchanged (hash %s) — reusing verdict, council calls so far=%d",
            label, run_id, key[1][:12], calls_for(run_id),
        )
        return _verdicts[key], CACHED

    _calls[run_id] = calls_for(run_id) + 1
    logger.info("[%s] run %s: council call #%d (hash %s)", label, run_id, _calls[run_id], key[1][:12])
    report = await run_council_fn()
    if not review_available(report):
        logger.warning(
            "[%s] run %s: no reviewer returned a score — review unavailable (not a failing verdict)",
            label, run_id,
        )
        return report, UNAVAILABLE
    _verdicts[key] = report
    return report, REVIEWED
