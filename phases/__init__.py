"""AetherOS phases package.

Exposes both the consolidated (p01–p11) phase supervisors and the _legacy
sub-phases that live under phases/_legacy/.

Bootstrap logic (runs once at import time)
─────────────────────────────────────────
1. sys.path — adds phases/_legacy/ so bare module names resolve:
      import p04a_backend_codegen          # works after this
2. __path__ extension — appends phases/_legacy/ to this package's __path__
   so fully-qualified sub-package imports resolve via Python's normal
   import machinery:
      from aether_os.phases.p04a_backend_codegen.task_agent import run
3. aether_os.phases alias — registers synthetic sys.modules entries so that
   legacy sub-packages' absolute imports (e.g.
   `from aether_os.phases.p04a_backend_codegen.supervisor_agent import …`)
   work regardless of whether the project is installed as a package
   (import path = aether_os.phases) or run directly with PYTHONPATH=.
   (import path = phases).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ── 1. sys.path — bare import support ────────────────────────────────────────
_legacy_dir = str(Path(__file__).parent / "_legacy")
if _legacy_dir not in sys.path:
    sys.path.insert(0, _legacy_dir)

# ── 2. __path__ — fully-qualified import support ──────────────────────────────
# Appending _legacy_dir to __path__ means Python's importer will look there
# when resolving aether_os.phases.<subpackage> or phases.<subpackage>.
if _legacy_dir not in __path__:
    __path__.append(_legacy_dir)  # type: ignore[name-defined]

# ── 3. aether_os.phases alias ─────────────────────────────────────────────────
# When the project root is on PYTHONPATH (PYTHONPATH=. from ~/Desktop/aether_os)
# this module is importable as "phases" not "aether_os.phases".  Legacy
# sub-packages use the fully-qualified "aether_os.phases.*" form.  Register
# synthetic sys.modules entries so those imports resolve in both contexts.
_this_module = sys.modules[__name__]

if "aether_os" not in sys.modules:
    _aether_pkg = types.ModuleType("aether_os")
    _aether_pkg.__path__ = [str(Path(__file__).parent.parent)]  # type: ignore[attr-defined]
    _aether_pkg.__package__ = "aether_os"
    _aether_pkg.__spec__ = None  # type: ignore[assignment]
    sys.modules["aether_os"] = _aether_pkg

if "aether_os.phases" not in sys.modules:
    sys.modules["aether_os.phases"] = _this_module
