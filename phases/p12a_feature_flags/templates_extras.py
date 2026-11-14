"""
Extra code generation templates for p12a_feature_flags.

Split from templates.py to keep both files under 600 lines.
Contains: FLAG_ADMIN_ROUTER_PY, INITIAL_FLAGS_JSON,
          ADD_FEATURE_FLAGS_SQL, TEST_FEATURE_FLAGS_PY.
"""
from __future__ import annotations

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

try:  # the generated backend's admin dependency (src/auth.py)
    from src.auth import require_admin
except ImportError:
    try:
        from auth import require_admin
    except ImportError:
        async def require_admin():
            # Fail closed: flag administration must never be reachable without admin auth.
            raise HTTPException(status_code=503, detail="flag admin disabled: src.auth.require_admin not found")

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flags", tags=["Feature Flags"], dependencies=[Depends(require_admin)])
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
    """Set rollout percentage for a flag (0.0-100.0)."""
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


def test_is_in_rollout_100pct():
    enable("full_rollout_flag")
    set_rollout_percentage("full_rollout_flag", 100.0)
    assert is_in_rollout("full_rollout_flag", "any_user")


def test_is_in_rollout_0pct():
    enable("zero_pct_flag")
    set_rollout_percentage("zero_pct_flag", 0.0)
    assert not is_in_rollout("zero_pct_flag", "any_user")


def test_is_in_rollout_disabled_flag():
    set_rollout_percentage("disabled_flag", 100.0)  # setting a percentage also enables the flag
    disable("disabled_flag")
    assert not is_in_rollout("disabled_flag", "any_user")


def test_is_in_rollout_partial_consistency():
    enable("half_flag")
    set_rollout_percentage("half_flag", 50.0)
    result_a = is_in_rollout("half_flag", "user_abc")
    result_b = is_in_rollout("half_flag", "user_abc")
    assert result_a == result_b


def test_set_rollout_percentage_enables_flag():
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
