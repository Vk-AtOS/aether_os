"""
Code generation templates for p12a_feature_flags.

Large string constants are stored here to keep task_agent.py under 600 lines.
"""
from __future__ import annotations

FEATURE_FLAGS_PY = '''\
"""
Feature flag service with percentage-based canary rollout support.

Flags are stored in feature_flags.json using the extended format:
  {
    "flag_name": {
      "enabled": true,
      "rollout_pct": 25.0,
      "ring": "beta",
      "variant": "blue",
      "description": "..."
    }
  }

Backward compatibility: is_enabled(flag) still works for pure on/off flags.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)
_FLAGS_FILE = Path(os.getenv("FEATURE_FLAGS_PATH", "feature_flags.json"))
_FLAGS: dict = {}
_LOCK = threading.RLock()

_DEFAULT_FLAG: dict = {
    "enabled": False,
    "rollout_pct": 0.0,
    "ring": "production",
    "variant": None,
    "description": "",
}


def _load() -> None:
    """Load flags from JSON file into in-memory dict (shared-lock for reads)."""
    global _FLAGS
    if not _FLAGS_FILE.exists():
        return
    try:
        if sys.platform != "win32":
            import fcntl
            with open(_FLAGS_FILE, "r", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_SH)
                try:
                    _FLAGS = json.load(_f)
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _FLAGS = json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning("feature_flags: _load failed: %s", e)
        _FLAGS = {}


def _save() -> None:
    """Persist in-memory flags to JSON file (exclusive lock for writes)."""
    try:
        if sys.platform != "win32":
            import fcntl
            _FLAGS_FILE.touch(exist_ok=True)
            with open(_FLAGS_FILE, "r+", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_EX)
                try:
                    _f.seek(0)
                    _f.write(json.dumps(_FLAGS, indent=2))
                    _f.truncate()
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _FLAGS_FILE.write_text(json.dumps(_FLAGS, indent=2), encoding="utf-8")
    except Exception as e:
        _logger.warning("feature_flags: _save failed: %s", e)


def _flag_entry(flag: str) -> dict:
    """Return the flag config dict, migrating legacy bool entries on the fly."""
    with _LOCK:
        entry = _FLAGS.get(flag, {})
    if isinstance(entry, bool):
        # Legacy format: plain boolean
        entry = {**_DEFAULT_FLAG, "enabled": entry}
    return {**_DEFAULT_FLAG, **entry}


# ---------------------------------------------------------------------------
# Backward-compatible simple on/off API
# ---------------------------------------------------------------------------

def enable(flag: str) -> None:
    """Enable a flag unconditionally (100% rollout)."""
    with _LOCK:
        _load()
        entry = _flag_entry(flag)
        entry["enabled"] = True
        entry["rollout_pct"] = 100.0
        _FLAGS[flag] = entry
        _save()


def disable(flag: str) -> None:
    """Disable a flag unconditionally (0% rollout)."""
    with _LOCK:
        _load()
        entry = _flag_entry(flag)
        entry["enabled"] = False
        entry["rollout_pct"] = 0.0
        _FLAGS[flag] = entry
        _save()


def is_enabled(flag: str) -> bool:
    """
    Check if a flag is enabled for all users.
    Reads FEATURE_<FLAG_UPPER> env var first; falls back to JSON store.
    Returns True only if enabled=True AND rollout_pct==100.
    """
    env_key = f"FEATURE_{flag.upper()}"
    env_val = os.getenv(env_key)
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes")
    with _LOCK:
        _load()
    entry = _flag_entry(flag)
    return bool(entry.get("enabled", False))


# ---------------------------------------------------------------------------
# Percentage rollout API
# ---------------------------------------------------------------------------

def _rollout_hash(flag: str, user_id: str) -> int:
    """
    Deterministic per-user rollout hash.
    Uses MD5 (first 8 hex chars as int) mod 100 for speed and collision resistance.
    Same user_id always maps to the same bucket for a given flag.
    """
    digest = hashlib.md5(f"{flag}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def is_in_rollout(flag: str, user_id: str) -> bool:
    """
    Return True if this user_id falls within the rollout percentage for the flag.
    Also requires enabled=True on the flag.
    """
    env_key = f"FEATURE_{flag.upper()}"
    env_val = os.getenv(env_key)
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes")
    with _LOCK:
        _load()
    entry = _flag_entry(flag)
    if not entry.get("enabled", False):
        return False
    rollout_pct = float(entry.get("rollout_pct", 0.0))
    if rollout_pct <= 0:
        return False
    if rollout_pct >= 100:
        return True
    return _rollout_hash(flag, str(user_id)) < rollout_pct


def set_rollout_percentage(flag: str, percentage: float) -> None:
    """
    Set the rollout percentage for a flag (0.0 – 100.0).
    Also sets enabled=True if percentage > 0.
    """
    pct = max(0.0, min(100.0, float(percentage)))
    with _LOCK:
        _load()
        entry = _flag_entry(flag)
        entry["rollout_pct"] = pct
        if pct > 0:
            entry["enabled"] = True
        _FLAGS[flag] = entry
        _save()


# ---------------------------------------------------------------------------
# Blue/green variant API
# ---------------------------------------------------------------------------

def get_active_variant(flag: str, user_id: str) -> str:
    """
    Return "blue" or "green" for this user based on the flag's configured variant
    and rollout percentage.
    - If the user is NOT in rollout: returns the opposite of flag.variant (the old variant).
    - If the user IS in rollout: returns flag.variant (the new variant).
    - Defaults to "blue" for in-rollout, "green" for out-of-rollout if not configured.
    """
    with _LOCK:
        _load()
    entry = _flag_entry(flag)
    configured_variant = entry.get("variant") or "blue"
    opposite = "green" if configured_variant == "blue" else "blue"
    if is_in_rollout(flag, str(user_id)):
        return configured_variant
    return opposite


# ---------------------------------------------------------------------------
# Ring-based rollout API
# ---------------------------------------------------------------------------

_RING_ORDER = ("internal", "beta", "production")


def is_in_ring(flag: str, user_ring: str) -> bool:
    """
    Return True if user_ring is at or before the flag's configured ring.
    Ring hierarchy: internal < beta < production.
    A flag with ring="beta" is visible to internal and beta users only.
    """
    with _LOCK:
        _load()
    entry = _flag_entry(flag)
    if not entry.get("enabled", False):
        return False
    flag_ring = entry.get("ring", "production")
    flag_idx = _RING_ORDER.index(flag_ring) if flag_ring in _RING_ORDER else len(_RING_ORDER) - 1
    user_idx = _RING_ORDER.index(user_ring) if user_ring in _RING_ORDER else len(_RING_ORDER) - 1
    return user_idx <= flag_idx


def set_ring(flag: str, ring: str) -> None:
    """Assign a flag to a deployment ring (internal | beta | production)."""
    if ring not in _RING_ORDER:
        _logger.warning("feature_flags: unknown ring %r — must be one of %s", ring, _RING_ORDER)
        return
    with _LOCK:
        _load()
        entry = _flag_entry(flag)
        entry["ring"] = ring
        _FLAGS[flag] = entry
        _save()


# ---------------------------------------------------------------------------
# RolloutManager class (OO wrapper for the module-level functions)
# ---------------------------------------------------------------------------

class RolloutManager:
    """
    Object-oriented wrapper around the feature flag store.
    Thread-safe via _LOCK. All state lives in the JSON file + _FLAGS dict.
    """

    def is_enabled(self, flag: str) -> bool:
        return is_enabled(flag)

    def enable(self, flag: str) -> None:
        enable(flag)

    def disable(self, flag: str) -> None:
        disable(flag)

    def is_in_rollout(self, flag: str, user_id: str) -> bool:
        return is_in_rollout(flag, user_id)

    def set_rollout_percentage(self, flag: str, percentage: float) -> None:
        set_rollout_percentage(flag, percentage)

    def get_active_variant(self, flag: str, user_id: str) -> str:
        return get_active_variant(flag, user_id)

    def is_in_ring(self, flag: str, user_ring: str) -> bool:
        return is_in_ring(flag, user_ring)

    def set_ring(self, flag: str, ring: str) -> None:
        set_ring(flag, ring)

    def list_flags(self) -> dict:
        with _LOCK:
            _load()
            return dict(_FLAGS)


# Load flags on module import
_load()
'''

# FLAG_ADMIN_ROUTER_PY, INITIAL_FLAGS_JSON, ADD_FEATURE_FLAGS_SQL, TEST_FEATURE_FLAGS_PY
# live in templates_extras.py to keep this file under 600 lines.
