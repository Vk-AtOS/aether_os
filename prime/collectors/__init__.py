"""Prime — registry of learning collectors (KAN-228). Collectors themselves arrive with L2/L3 (KAN-230, KAN-231).

A collector is an async function (org_id, user_id) -> iterable of Learned, defined in a module of this package and
registered with @collector(name, source). It only READS its source and returns what it found; it never stores.
`run(name, org_id, user_id)` is the only way to run one: it calls consent.allowed() first (the collector is not
called at all without consent) and stores through learned.record(), which checks again. So a collector cannot skip
the consent check; tests/test_prime_consent_enforcement.py scans these modules and fails on one that tries
(an unregistered public function, or one that touches the session, the table or learned.record itself).
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

from aether_os.prime import consent, learned


@dataclass(frozen=True)
class Learned:
    kind: str
    summary: str
    data: Optional[Dict[str, Any]] = field(default=None)


Collect = Callable[[str, str], Awaitable[Iterable[Learned]]]
REGISTRY: Dict[str, Tuple[str, Collect]] = {}


def collector(name: str, source: str) -> Callable[[Collect], Collect]:
    if source not in consent.SOURCES:
        raise ValueError(f"unknown source {source!r}: one of {consent.SOURCES}")

    def register(fn: Collect) -> Collect:
        if name in REGISTRY:
            raise ValueError(f"collector {name!r} is registered twice")
        REGISTRY[name] = (source, fn)
        return fn
    return register


async def run(name: str, org_id: str, user_id: str) -> int:
    """Collect for one person from the collector's source. Returns how many items were stored (0 without consent)."""
    source, fn = REGISTRY[name]
    if not await consent.allowed(org_id, user_id, source):
        return 0
    stored = 0
    for item in await fn(org_id, user_id):
        if await learned.record(org_id, user_id, source, item.kind, item.summary, item.data):
            stored += 1
    return stored


def load_all() -> Dict[str, Tuple[str, Collect]]:
    """Import every collector module so the registry is complete."""
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY
