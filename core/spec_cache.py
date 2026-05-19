"""Spec template cache — reuse architecture.json for same-domain projects.

Cache key: SHA256(domain + sorted detected entity table names).
Cache location: ~/.aether_os/spec_cache/<key>.json

Usage:
    arch = spec_cache.get(domain, entities)   # None on miss
    spec_cache.put(domain, entities, arch)    # save after success
"""
from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".aether_os" / "spec_cache"
_MAX_CACHE_ENTRIES = 200


def _cache_key(domain: str, entity_tables: List[str]) -> str:
    payload = domain + "|" + ",".join(sorted(entity_tables))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}.json"


def get(domain: str, entity_tables: List[str]) -> Optional[Dict]:
    """Return cached architecture dict, or None on miss."""
    if not entity_tables:
        return None
    key = _cache_key(domain, entity_tables)
    path = _cache_path(key)
    if path.exists():
        try:
            arch = json.loads(path.read_text())
            logger.info("[spec_cache] HIT key=%s domain=%s entities=%s", key, domain, entity_tables)
            return arch
        except Exception as exc:
            logger.warning("[spec_cache] corrupt entry %s: %s", path, exc)
            path.unlink(missing_ok=True)
    return None


def put(domain: str, entity_tables: List[str], arch: Dict) -> None:
    """Save architecture to cache. Silently ignores errors."""
    if not entity_tables or not arch:
        return
    # Prune if cache is too large
    try:
        entries = sorted(_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(entries) >= _MAX_CACHE_ENTRIES:
            entries.pop(0).unlink(missing_ok=True)
    except Exception:
        pass
    key = _cache_key(domain, entity_tables)
    try:
        _cache_path(key).write_text(json.dumps(arch, indent=2))
        logger.info("[spec_cache] SAVED key=%s domain=%s entities=%s", key, domain, entity_tables)
    except Exception as exc:
        logger.warning("[spec_cache] could not save: %s", exc)
