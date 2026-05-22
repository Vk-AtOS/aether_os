"""AetherOS phases package.

Exposes the consolidated (p01–p14) phase supervisors and the p08_cicd
CI engine (webhook, DFLE, repair pipeline).

Bootstrap logic (runs once at import time)
─────────────────────────────────────────
aether_os.phases alias — registers synthetic sys.modules entries so that
sub-packages' absolute imports (e.g.
`from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph`)
work regardless of whether the project is installed as a package
(import path = aether_os.phases) or run directly with PYTHONPATH=.
(import path = phases).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ── aether_os.phases alias ────────────────────────────────────────────────────
# When the project root is on PYTHONPATH (PYTHONPATH=. from ~/Desktop/aether_os)
# this module is importable as "phases" not "aether_os.phases".  Sub-packages
# use the fully-qualified "aether_os.phases.*" form.  Register synthetic
# sys.modules entries so those imports resolve in both contexts.
_this_module = sys.modules[__name__]

if "aether_os" not in sys.modules:
    _aether_pkg = types.ModuleType("aether_os")
    _aether_pkg.__path__ = [str(Path(__file__).parent.parent)]  # type: ignore[attr-defined]
    _aether_pkg.__package__ = "aether_os"
    _aether_pkg.__spec__ = None  # type: ignore[assignment]
    sys.modules["aether_os"] = _aether_pkg

if "aether_os.phases" not in sys.modules:
    sys.modules["aether_os.phases"] = _this_module
