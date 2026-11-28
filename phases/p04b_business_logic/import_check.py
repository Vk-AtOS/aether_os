"""p04b: a model-written module must import, not just parse.

Production run 32 (23 Nov 2026): the model's workflow_engine.py parsed and named nothing undefined, but its class body
called WorkflowState("trialing") for an invented Subscription workflow whose states were never added to the enum.
That raises at import time, so the generated app's main.py could not import: pytest collected nothing (s06 failed)
and every entity endpoint answered 500. import_error() imports the module in the sandbox (like p04_backend's own
checks) and returns the exception text; the caller then uses its deterministic fallback.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from aether_os.core.sandbox.runner import SandboxUnavailable

logger = logging.getLogger(__name__)

_CHECK = """\
import importlib, sys
sys.path.insert(0, '.')
try:
    importlib.import_module({module!r})
except ModuleNotFoundError as e:   # a dependency the sandbox lacks: not a defect of the module itself
    print('MISSING', e)
except Exception as e:
    print('IMPORT_FAILED', type(e).__name__ + ': ' + str(e)[:300])
    sys.exit(3)
"""


async def import_error(code: str, module: str, work_dir: Path) -> Optional[str]:
    """"<ExcType>: message" when importing `code` as `module` raises, else None (also None when it cannot be judged:
    test env, or only a missing third-party dependency). Raises SandboxUnavailable when the sandbox cannot run it: the
    check used to be skipped silently, so modules shipped unchecked (KAN-245)."""
    if os.environ.get("ENVIRONMENT") == "test":
        return None
    from aether_os.core.sandbox import phase_exec
    tmp = Path(tempfile.mkdtemp(prefix="p04b_import_", dir=str(work_dir)))
    try:
        (tmp / f"{module}.py").write_text(code)
        res = await phase_exec.run(["python3", "-c", _CHECK.format(module=module)], cwd=tmp, timeout=30, text=True)
        if res.returncode == 3:
            out = (res.stdout or "") + (res.stderr or "")
            line = next((ln for ln in out.splitlines() if ln.startswith("IMPORT_FAILED")), out.strip()[-300:])
            return line.replace("IMPORT_FAILED ", "", 1)
        return None
    except SandboxUnavailable:
        raise   # the generated code was not run: the phase fails loudly instead of skipping the check
    except Exception as e:
        logger.warning("p04b: import check for %s could not run: %s", module, e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
