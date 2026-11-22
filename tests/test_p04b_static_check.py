"""Model-written business logic with undefined names is refused for the deterministic fallback (run 19, 22 Nov 2026:
workflow_engine.py used `_apply_task_status_change` without defining it and the app no longer imported)."""
from __future__ import annotations

import shutil

import pytest

from aether_os.phases.p04b_business_logic.helpers import _FALLBACK_BUSINESS_RULES, _FALLBACK_WORKFLOW_ENGINE
from aether_os.core.codegen.static_check import undefined_names
from aether_os.phases.p04b_business_logic.task_agent import _validate_python_output
from aether_os.phases.p07a_unit_testing.crud_repair import _may_patch

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


def test_p07a_repair_may_patch_the_module_the_traceback_names(tmp_path):
    src = tmp_path / "src"
    (src / "routers").mkdir(parents=True)
    (src / "tests").mkdir()
    crud = src / "routers" / "crud.py"
    for f in (crud, src / "workflow_engine.py", src / "models.py", src / "tests" / "test_x.py", src / "conftest.py"):
        f.write_text("")
    err = 'File "/app/src/workflow_engine.py", line 4\nNameError: name \'_apply_task_status_change\' is not defined'
    allowed = _may_patch(src, crud, err)
    assert allowed(crud.resolve()) and allowed((src / "workflow_engine.py").resolve())
    assert not allowed((src / "models.py").resolve())                   # not named by the traceback
    assert not allowed((src / "tests" / "test_x.py").resolve())
    assert not allowed((src / "conftest.py").resolve())
    assert not allowed((tmp_path / "outside.py").resolve())
