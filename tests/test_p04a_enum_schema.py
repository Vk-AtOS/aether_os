"""Run da281716 (team task tracker): Task.status is a required enum (todo/doing/done). p04a put
CheckConstraint("status IN (...)") on the column but typed the schema field as plain `str`, so OpenAPI published no
values, the generated unit tests posted status="test_status1", and the database answered 409 for every create:
test_create and the CRUD round trip failed, healing exhausted its 5 attempts and s07 blocked the run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest
from pydantic import ValidationError

from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from aether_os.phases.p04a_backend_codegen.ir_generators import generate_schemas_py
from tests.test_p04a_generated_backend import generate

TASK_IR = {
    "domain": "general", "app_name": "Tracker",
    "entities": [{"name": "Task", "table": "tasks", "fields": [
        {"name": "title", "type": "string", "nullable": False},
        {"name": "status", "type": "enum", "nullable": False, "enum_values": ["todo", "doing", "done"], "default": "todo"},
        {"name": "priority", "type": "enum", "nullable": True, "enum_values": ["low", "high"]}]}],
    "business_rules": [],
    "permissions": [{"role": "admin", "entity": "Task", "actions": ["read", "create", "update", "delete"]}],
}


def _schemas():
    ir = DomainIR(domain="general", app_name="Tracker")
    ir.entities = [IREntity("Task", "tasks", [IRField(**f) for f in TASK_IR["entities"][0]["fields"]])]
    mod = types.ModuleType("generated_enum_schemas")
    sys.modules[mod.__name__] = mod
    exec(generate_schemas_py(ir), mod.__dict__)    # noqa: S102
    return mod.__dict__


def test_enum_fields_accept_only_their_values_and_publish_them():
    ns = _schemas()
    assert ns["TaskCreate"](title="t", status="doing").status == "doing"
    with pytest.raises(ValidationError):
        ns["TaskCreate"](title="t", status="test_status1")       # 422 at the API, not a 409 from the database
    assert ns["TaskCreate"].model_json_schema()["properties"]["status"]["enum"] == ["todo", "doing", "done"]
    # nullable enum and the all-optional update schema keep a well-formed Optional[Literal[...]]
    assert ns["TaskCreate"](title="t", status="todo", priority=None).priority is None
    assert ns["TaskUpdate"](priority="high").priority == "high"
    with pytest.raises(ValidationError):
        ns["TaskUpdate"](status="nope")


def test_generated_crud_tests_pass_for_a_required_enum(tmp_path, monkeypatch):
    from aether_os.phases.p07a_unit_testing.task_agent import _generate_crud_tests

    monkeypatch.setenv("ENVIRONMENT", "test")
    _result, app = generate(tmp_path, domain="general", monkeypatch=monkeypatch, ir_override=TASK_IR)
    tests = app / "tests"
    tests.mkdir(exist_ok=True)
    entities = [{"name": "Task", "table": "tasks", "fields": [{"name": "title", "type": "string"}]}]
    (tests / "test_crud.py").write_text(_generate_crud_tests(app / "src", "Tracker", entities))
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/t.db", "SECRET_KEY": "x" * 40,
           "ENVIRONMENT": "test", "ALLOW_SIGNUP": "true", "PYTHONPATH": ""}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore",
                           "-o", "asyncio_mode=strict", str(tests / "test_crud.py")],
                          cwd=app, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]
