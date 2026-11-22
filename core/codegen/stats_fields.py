"""Which entity fields drive the generated /stats numbers (shared by the p04a backend and the p05 dashboard).

Both sides must agree on what an "overdue" count is, so the rule lives in one place: an entity has one when it
has a date-like due field and a status/stage field. Deterministic, a pure function of the entity's fields.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

_DUE = re.compile(r"(^|_)(due|deadline)(_|$)")
STATUS_NAMES = ("status", "stage")
# Statuses that mean "no longer pending"; compared lower-cased.
DONE_STATUSES = ("done", "completed", "complete", "closed", "resolved", "cancelled", "canceled", "archived",
                 "delivered", "paid", "won", "lost")


def _kind(t: object) -> str:
    """'date' / 'datetime' / '' for an IR type (enum, 'date', 'AetherType.DATETIME', ...)."""
    s = str(getattr(t, "value", t) or "").lower().rsplit(".", 1)[-1]
    return s if s in ("date", "datetime") else ""


def overdue_fields(fields: Iterable[Tuple[str, object]]) -> Optional[Tuple[str, str, str]]:
    """(due_field, due_kind, status_field) when the entity can have overdue rows, else None.

    ``fields`` are (name, type) pairs; a due field must be date/datetime typed."""
    pairs = list(fields)
    status = next((n for n, _ in pairs if n in STATUS_NAMES), None)
    due = next(((n, _kind(t)) for n, t in pairs if _DUE.search(n) and _kind(t)), None)
    return (due[0], due[1], status) if status and due else None


def stage_slug(value: object) -> str:
    """Key suffix of an enum value in /stats (stage_<slug>); same rule the stats router uses."""
    return re.sub(r"\W+", "_", str(value).lower()).strip("_") or "value"
