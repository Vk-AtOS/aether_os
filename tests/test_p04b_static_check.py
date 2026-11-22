"""Model-written business logic with undefined names is refused for the deterministic fallback (run 19, 22 Nov 2026:
workflow_engine.py used `_apply_task_status_change` without defining it and the app no longer imported)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aether_os.phases.p04b_business_logic.helpers import _FALLBACK_BUSINESS_RULES, _FALLBACK_WORKFLOW_ENGINE
from aether_os.phases.p04b_business_logic.static_check import undefined_names
from aether_os.phases.p04b_business_logic.task_agent import _validate_python_output

needs_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not on PATH")

RUN19 = ("TRANSITIONS = {'done': _apply_task_status_change}\n"
         "class WorkflowEngine:\n    pass\n")


@needs_ruff
def test_run_19_undefined_name_is_reported():
    errs = undefined_names(RUN19, "workflow_engine.py")
    assert errs and "_apply_task_status_change" in errs[0] and "line 1" in errs[0]
    assert _validate_python_output(RUN19, "workflow_engine.py")


@needs_ruff
def test_clean_code_passes():
    assert undefined_names("def f(x):\n    return x + 1\n", "m.py") == []


@needs_ruff
@pytest.mark.parametrize("template", [_FALLBACK_WORKFLOW_ENGINE, _FALLBACK_BUSINESS_RULES])
def test_the_fallbacks_themselves_are_clean(template):
    code = template.format(domain="saas", project_name="x")
    assert _validate_python_output(code, "fallback.py") == []
