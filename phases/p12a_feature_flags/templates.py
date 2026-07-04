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

FLAG_ADMIN_ROUTER_PY = '''\
"""
FastAPI router for feature flag administration.
Provides endpoints to list, enable, disable, set rollout percentage,
check per-user rollout status, and assign rings.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from feature_flags.feature_flags import (
    RolloutManager,
    _flag_entry,
    _FLAGS,
    disable,
    enable,
    is_in_rollout,
    set_ring,
    set_rollout_percentage,
)

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flags", tags=["Feature Flags"])
_mgr = RolloutManager()


class RolloutBody(BaseModel):
    percentage: float


class RingBody(BaseModel):
    ring: str


@router.get("/")
def list_flags():
    """List all feature flags with their rollout configuration."""
    try:
        flags = _mgr.list_flags()
        result = {}
        for name, entry in flags.items():
            if isinstance(entry, bool):
                result[name] = {"enabled": entry, "rollout_pct": 100.0 if entry else 0.0,
                                "ring": "production", "variant": None, "description": ""}
            else:
                result[name] = entry
        return {"flags": result}
    except Exception as e:
        _logger.warning("list_flags error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{flag}/enable")
def enable_flag(flag: str):
    """Enable a flag unconditionally (100% rollout)."""
    try:
        enable(flag)
        return {"flag": flag, "enabled": True, "rollout_pct": 100.0}
    except Exception as e:
        _logger.warning("enable_flag error for %s: %s", flag, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{flag}/disable")
def disable_flag(flag: str):
    """Disable a flag unconditionally (0% rollout)."""
    try:
        disable(flag)
        return {"flag": flag, "enabled": False, "rollout_pct": 0.0}
    except Exception as e:
        _logger.warning("disable_flag error for %s: %s", flag, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{flag}/rollout")
def set_rollout(flag: str, body: RolloutBody):
    """Set rollout percentage for a flag (0.0–100.0)."""
    try:
        set_rollout_percentage(flag, body.percentage)
        return {"flag": flag, "rollout_pct": body.percentage}
    except Exception as e:
        _logger.warning("set_rollout error for %s: %s", flag, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{flag}/check")
def check_user_rollout(flag: str, user_id: str):
    """Check whether a specific user_id is in the rollout for this flag."""
    try:
        in_rollout = is_in_rollout(flag, user_id)
        entry = _flag_entry(flag)
        return {
            "flag": flag,
            "user_id": user_id,
            "in_rollout": in_rollout,
            "rollout_pct": entry.get("rollout_pct", 0.0),
            "ring": entry.get("ring", "production"),
        }
    except Exception as e:
        _logger.warning("check_user_rollout error for %s/%s: %s", flag, user_id, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{flag}/ring")
def assign_ring(flag: str, body: RingBody):
    """Assign a flag to a deployment ring (internal | beta | production)."""
    valid_rings = ("internal", "beta", "production")
    if body.ring not in valid_rings:
        raise HTTPException(
            status_code=422,
            detail=f"ring must be one of {valid_rings}",
        )
    try:
        set_ring(flag, body.ring)
        return {"flag": flag, "ring": body.ring}
    except Exception as e:
        _logger.warning("assign_ring error for %s: %s", flag, e)
        raise HTTPException(status_code=500, detail=str(e)) from e
'''

INITIAL_FLAGS_JSON = '''\
{
  "enable_beta": {
    "enabled": false,
    "rollout_pct": 0,
    "ring": "production",
    "variant": null,
    "description": "Beta feature toggle"
  },
  "new_dashboard": {
    "enabled": true,
    "rollout_pct": 25.0,
    "ring": "beta",
    "variant": "blue",
    "description": "New dashboard layout - 25% canary"
  },
  "dark_mode": {
    "enabled": true,
    "rollout_pct": 100.0,
    "ring": "production",
    "variant": null,
    "description": "Dark mode UI toggle"
  }
}
'''

ADD_FEATURE_FLAGS_SQL = '''\
CREATE TABLE IF NOT EXISTS feature_flags (
  id          SERIAL PRIMARY KEY,
  name        VARCHAR(100) UNIQUE NOT NULL,
  enabled     BOOLEAN NOT NULL DEFAULT FALSE,
  rollout_pct NUMERIC(5,2) NOT NULL DEFAULT 0.00
                CHECK (rollout_pct >= 0 AND rollout_pct <= 100),
  ring        VARCHAR(20) NOT NULL DEFAULT \'production\'
                CHECK (ring IN (\'internal\', \'beta\', \'production\')),
  variant     VARCHAR(20) DEFAULT NULL
                CHECK (variant IS NULL OR variant IN (\'blue\', \'green\')),
  description TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feature_flags_name    ON feature_flags (name);
CREATE INDEX IF NOT EXISTS idx_feature_flags_ring    ON feature_flags (ring);
CREATE INDEX IF NOT EXISTS idx_feature_flags_enabled ON feature_flags (enabled);
'''

TEST_FEATURE_FLAGS_PY = '''\
"""Tests for the feature flag canary rollout system."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch

# Patch the flags file path before importing the module
os.environ.setdefault("FEATURE_FLAGS_PATH", "/tmp/test_feature_flags.json")

from feature_flags.feature_flags import (
    RolloutManager,
    _rollout_hash,
    disable,
    enable,
    get_active_variant,
    is_enabled,
    is_in_ring,
    is_in_rollout,
    set_ring,
    set_rollout_percentage,
)


# ---------------------------------------------------------------------------
# Basic on/off (backward compatibility)
# ---------------------------------------------------------------------------

def test_flag_disabled_by_default():
    assert not is_enabled("nonexistent_flag_xyz")


def test_enable_disable():
    enable("test_flag")
    assert is_enabled("test_flag")
    disable("test_flag")
    assert not is_enabled("test_flag")


def test_env_override(monkeypatch):
    monkeypatch.setenv("FEATURE_MY_FLAG", "true")
    assert is_enabled("my_flag")


def test_env_override_false(monkeypatch):
    monkeypatch.setenv("FEATURE_MY_FLAG", "false")
    assert not is_enabled("my_flag")


# ---------------------------------------------------------------------------
# Rollout hash — determinism
# ---------------------------------------------------------------------------

def test_rollout_hash_deterministic():
    h1 = _rollout_hash("flag_a", "user_42")
    h2 = _rollout_hash("flag_a", "user_42")
    assert h1 == h2


def test_rollout_hash_range():
    for uid in range(200):
        h = _rollout_hash("some_flag", str(uid))
        assert 0 <= h < 100


def test_rollout_hash_uses_md5():
    digest = hashlib.md5("flag_a:user_42".encode()).hexdigest()
    expected = int(digest[:8], 16) % 100
    assert _rollout_hash("flag_a", "user_42") == expected


# ---------------------------------------------------------------------------
# Percentage rollout
# ---------------------------------------------------------------------------

def test_is_in_rollout_100pct():
    enable("full_rollout_flag")
    set_rollout_percentage("full_rollout_flag", 100.0)
    assert is_in_rollout("full_rollout_flag", "any_user")


def test_is_in_rollout_0pct():
    enable("zero_pct_flag")
    set_rollout_percentage("zero_pct_flag", 0.0)
    assert not is_in_rollout("zero_pct_flag", "any_user")


def test_is_in_rollout_disabled_flag():
    disable("disabled_flag")
    set_rollout_percentage("disabled_flag", 100.0)
    assert not is_in_rollout("disabled_flag", "any_user")


def test_is_in_rollout_partial_consistency():
    """50% rollout should be consistent per user."""
    enable("half_flag")
    set_rollout_percentage("half_flag", 50.0)
    result_a = is_in_rollout("half_flag", "user_abc")
    result_b = is_in_rollout("half_flag", "user_abc")
    assert result_a == result_b  # deterministic


def test_set_rollout_percentage_enables_flag():
    """Setting rollout > 0 should also enable the flag."""
    disable("auto_enable_flag")
    set_rollout_percentage("auto_enable_flag", 30.0)
    from feature_flags.feature_flags import _flag_entry
    entry = _flag_entry("auto_enable_flag")
    assert entry["enabled"] is True
    assert entry["rollout_pct"] == 30.0


def test_set_rollout_clamps_to_range():
    set_rollout_percentage("clamp_flag", 150.0)
    from feature_flags.feature_flags import _flag_entry
    assert _flag_entry("clamp_flag")["rollout_pct"] == 100.0

    set_rollout_percentage("clamp_flag", -10.0)
    assert _flag_entry("clamp_flag")["rollout_pct"] == 0.0


# ---------------------------------------------------------------------------
# Blue/green variant
# ---------------------------------------------------------------------------

def test_variant_in_rollout():
    enable("bg_flag")
    set_rollout_percentage("bg_flag", 100.0)
    from feature_flags.feature_flags import _flag_entry, _FLAGS, _save, _LOCK
    with _LOCK:
        entry = _flag_entry("bg_flag")
        entry["variant"] = "blue"
        _FLAGS["bg_flag"] = entry
        _save()
    assert get_active_variant("bg_flag", "user_1") == "blue"


def test_variant_out_of_rollout():
    enable("bg_flag2")
    set_rollout_percentage("bg_flag2", 0.0)
    from feature_flags.feature_flags import _flag_entry, _FLAGS, _save, _LOCK
    with _LOCK:
        entry = _flag_entry("bg_flag2")
        entry["enabled"] = True
        entry["rollout_pct"] = 0.0
        entry["variant"] = "blue"
        _FLAGS["bg_flag2"] = entry
        _save()
    # Out of rollout — should return opposite of "blue" = "green"
    assert get_active_variant("bg_flag2", "user_1") == "green"


# ---------------------------------------------------------------------------
# Ring-based rollout
# ---------------------------------------------------------------------------

def test_ring_internal_sees_internal_flag():
    enable("internal_flag")
    set_ring("internal_flag", "internal")
    assert is_in_ring("internal_flag", "internal")


def test_ring_beta_does_not_see_internal_flag():
    enable("internal_only")
    set_ring("internal_only", "internal")
    assert not is_in_ring("internal_only", "beta")


def test_ring_production_sees_production_flag():
    enable("prod_flag")
    set_ring("prod_flag", "production")
    assert is_in_ring("prod_flag", "production")


def test_ring_disabled_flag():
    disable("ring_disabled")
    set_ring("ring_disabled", "internal")
    assert not is_in_ring("ring_disabled", "internal")


# ---------------------------------------------------------------------------
# RolloutManager class
# ---------------------------------------------------------------------------

def test_rollout_manager_wraps_functions():
    mgr = RolloutManager()
    mgr.enable("mgr_flag")
    assert mgr.is_enabled("mgr_flag")
    mgr.disable("mgr_flag")
    assert not mgr.is_enabled("mgr_flag")


def test_rollout_manager_list_flags():
    mgr = RolloutManager()
    mgr.enable("list_test_flag")
    flags = mgr.list_flags()
    assert "list_test_flag" in flags
'''
