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


import pytest


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
