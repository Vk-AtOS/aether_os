"""Production run 32 (23 Nov 2026): the model's workflow_engine.py parsed and named nothing undefined, but its class body
called WorkflowState("trialing") for an invented Subscription workflow. That raises at import, so the generated app
could not start (s06: pytest collected nothing; every entity endpoint 500). Such a module must be refused."""
from __future__ import annotations

import asyncio
import inspect
import subprocess

import pytest

from aether_os.phases.p04b_business_logic import import_check, task_agent
from aether_os.phases.p04b_business_logic.helpers import _FALLBACK_BUSINESS_RULES, _FALLBACK_WORKFLOW_ENGINE
from aether_os.phases.p04b_business_logic.task_agent import _validate_python_output

RUN32 = '''from enum import Enum


class WorkflowState(str, Enum):
    TASK_TODO = "TODO"


class WorkflowEngine:
    WORKFLOWS = {"Subscription": [WorkflowState("trialing")]}
'''


@pytest.fixture
def local_sandbox(monkeypatch):
    """Run the import check as a plain subprocess (the sandbox is not available in unit tests)."""
    from aether_os.core.sandbox import phase_exec

    async def run(argv, cwd=None, timeout=None, text=True, **kw):
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)

    monkeypatch.setattr(phase_exec, "run", run)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def test_run_32_module_passes_the_static_check_but_fails_to_import(local_sandbox, tmp_path):
    assert not [e for e in _validate_python_output(RUN32, "workflow_engine.py") if "SyntaxError" in e]
    err = asyncio.run(import_check.import_error(RUN32, "workflow_engine", tmp_path))
    assert err and err.startswith("ValueError") and "trialing" in err
    assert list(tmp_path.iterdir()) == []                       # the scratch copy is removed


@pytest.mark.parametrize("template,module", [(_FALLBACK_WORKFLOW_ENGINE, "workflow_engine"),
                                             (_FALLBACK_BUSINESS_RULES, "business_rules")])
def test_the_fallbacks_import(local_sandbox, tmp_path, template, module):
    code = template.format(domain="saas", project_name="x")
    assert asyncio.run(import_check.import_error(code, module, tmp_path)) is None


def test_a_missing_third_party_package_is_not_held_against_the_module(local_sandbox, tmp_path):
    assert asyncio.run(import_check.import_error("import some_package_that_is_not_installed\n", "m", tmp_path)) is None


def test_both_model_written_modules_are_import_checked_before_they_are_written():
    src = inspect.getsource(task_agent)
    assert 'import_error(workflow_engine_code, "workflow_engine"' in src
    assert 'import_error(business_rules_code, "business_rules"' in src
    assert "invent entities (no expense reports" in src          # the prompt no longer seeds foreign workflows
