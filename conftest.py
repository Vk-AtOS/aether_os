"""
Pytest configuration for the agent worktree.

The worktree lives at a path that doesn't match "aether_os", so the standard
pythonpath = [".."] trick (which works in the main repo because
/Users/apple/Desktop/aether_os/ is found from /Users/apple/Desktop/) doesn't work
in the worktree. This conftest registers the worktree root as the `aether_os`
package so all `aether_os.*` imports resolve to the worktree's code.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import types
from pathlib import Path

# Worktree root is the directory that contains this conftest.py
_WORKTREE_ROOT = Path(__file__).parent.resolve()


def _register_aether_os_package() -> None:
    """Register the worktree root as the aether_os top-level package."""
    if "aether_os" in sys.modules:
        return  # Already registered (e.g. via editable install)

    # Create a module object for aether_os that acts as a namespace pointing
    # to the worktree root. Python's import system will then resolve
    # aether_os.core.* by looking in _WORKTREE_ROOT/core/*.
    mod = types.ModuleType("aether_os")
    mod.__file__ = str(_WORKTREE_ROOT / "__init__.py")
    mod.__path__ = [str(_WORKTREE_ROOT)]
    mod.__package__ = "aether_os"
    mod.__spec__ = importlib.util.spec_from_file_location(
        "aether_os",
        str(_WORKTREE_ROOT / "__init__.py"),
        submodule_search_locations=[str(_WORKTREE_ROOT)],
    )
    sys.modules["aether_os"] = mod


_register_aether_os_package()


import os

import pytest

# See gateway/lifespan.py: background monitors make test teardown flaky.
os.environ.setdefault("AETHER_DISABLE_MONITORS", "1")
# Guardian snapshot dumps default to ./snapshots/guardian inside the source tree and were committed
# (KAN-192/194); tests must never write into the repo.
os.environ.setdefault("GUARDIAN_SNAPSHOT_DIR", tempfile.mkdtemp(prefix="aether-snapshots-"))
# Runtime state (error registry, stage feedback) goes to a temp dir, never into the checkout (KAN-217).
os.environ.setdefault("AETHER_STATE_DIR", tempfile.mkdtemp(prefix="aether-state-"))


@pytest.fixture(autouse=True)
def _reset_pipeline_semaphore():
    """Reset the global pipeline semaphore before each test.

    _PIPELINE_SEMAPHORE is a module-level singleton.  When pytest-timeout kills
    a test mid-acquisition the semaphore is never released, causing every
    subsequent test that calls FactoryPipeline.run() to block forever.
    Resetting to None forces a fresh Semaphore for each test's event loop.
    """
    import aether_os.orchestrator.run_state as _rs
    _rs._PIPELINE_SEMAPHORE = None
    yield
    _rs._PIPELINE_SEMAPHORE = None


@pytest.fixture(autouse=True)
def _no_human_spec_review(monkeypatch):
    """Skip the human spec-review pause in tests.

    Runs default to approval_required, so after s01 the pipeline critiques the
    spec with a real model call and then waits up to 600 s for a person to
    approve. Pipeline tests mock the stages and have no person, so they hang.
    A test of the gate itself should import run_spec_review_gate directly.
    """
    async def _approved(**_kwargs):
        return None

    monkeypatch.setattr(
        "aether_os.orchestrator.spec_review_gate.run_spec_review_gate", _approved
    )
    yield
