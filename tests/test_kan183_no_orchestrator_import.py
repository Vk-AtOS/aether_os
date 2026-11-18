"""KAN-183: the LLM layer must not import the orchestrator (import cycle)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_model_router_does_not_load_orchestrator():
    code = ("import sys; import aether_os.core.model_router, aether_os.core.llm.providers; "
            "bad=[m for m in sys.modules if m.startswith('aether_os.orchestrator')]; "
            "print('LOADED', bad) if bad else print('CLEAN')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert "CLEAN" in out.stdout, out.stdout + out.stderr


def test_context_vars_are_the_same_objects():
    from aether_os.core import run_context
    from aether_os.orchestrator import events
    assert events.ACTIVE_RUN_ID is run_context.ACTIVE_RUN_ID
    assert events.ACTIVE_ORG_ID is run_context.ACTIVE_ORG_ID
