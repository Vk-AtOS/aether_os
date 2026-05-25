"""Spec template cache — reuse architecture.json for same-domain projects.

Cache key: SHA256(domain + sorted entity table names + SHA256(full req_text)).
Cache location: ~/.aether_os/spec_cache/<key>.json
TTL: 24 hours

Usage:
    arch = spec_cache.get(domain, entities, req_text)   # None on miss/expired
    spec_cache.put(domain, entities, arch, req_text)    # save after success
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".aether_os" / "spec_cache"
_MAX_CACHE_ENTRIES = 200
_TTL_SECONDS = 86400  # 24 hours


def _cache_key(domain: str, entity_tables: List[str], req_text: str = "") -> str:
    # PIPELINE-031: use full SHA256 hash of req_text, not truncated slice
    req_hash = hashlib.sha256(req_text.encode()).hexdigest() if req_text else ""
    payload = domain + "|" + ",".join(sorted(entity_tables)) + "|" + req_hash
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}.json"


def get(domain: str, entity_tables: List[str], req_text: str = "") -> Optional[Dict]:
    """Return cached architecture dict, or None on miss/expiry."""
    if not entity_tables:
        return None
    key = _cache_key(domain, entity_tables, req_text)
    path = _cache_path(key)
    if path.exists():
        try:
            entry = json.loads(path.read_text())
            # PIPELINE-032: check TTL
            created_at = entry.get("created_at", 0)
            if time.time() - created_at > _TTL_SECONDS:
                logger.info("[spec_cache] EXPIRED key=%s", key)
                path.unlink(missing_ok=True)
                return None
            arch = entry.get("data")
            if arch is None:
                # Legacy format (no envelope) — treat as expired
                path.unlink(missing_ok=True)
                return None
            logger.info("[spec_cache] HIT key=%s domain=%s entities=%s", key, domain, entity_tables)
            return arch
        except Exception as exc:
            logger.warning("[spec_cache] corrupt entry %s: %s", path, exc)
            path.unlink(missing_ok=True)
    return None


def put(domain: str, entity_tables: List[str], arch: Dict, req_text: str = "") -> None:
    """Save architecture to cache with TTL. Silently ignores errors."""
    if not entity_tables or not arch:
        return
    # Prune if cache is too large
    try:
        entries = sorted(_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(entries) >= _MAX_CACHE_ENTRIES:
            entries.pop(0).unlink(missing_ok=True)
    except Exception:
        pass
    key = _cache_key(domain, entity_tables, req_text)
    # PIPELINE-032: wrap entry with TTL metadata
    entry = {"data": arch, "created_at": time.time()}
    try:
        _cache_path(key).write_text(json.dumps(entry, indent=2))
        logger.info("[spec_cache] SAVED key=%s domain=%s entities=%s", key, domain, entity_tables)
    except Exception as exc:
        logger.warning("[spec_cache] could not save: %s", exc)
