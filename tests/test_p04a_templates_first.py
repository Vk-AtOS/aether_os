"""KAN-209: p04a builds models/schemas/CRUD from the normalised entity list with no model call, and the generated CRUD
tests pass against the generated backend for three entity sets.

The generated app has modules named main, models, auth, database, so its tests run in a pytest subprocess with the
app's src on sys.path (the way the generated tests do it); no sandbox or container is involved.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from aether_os.core.codegen.entities import entity_from_label, normalise_entities, templates_first_enabled
from aether_os.phases.p04a_backend_codegen import helpers, task_agent
from aether_os.phases.p07a_unit_testing.task_agent import _generate_crud_tests

MODS = ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx", "pytest_asyncio")

ONE = [{"name": "Task", "table": "tasks", "fields": [
    {"name": "title", "type": "string"}, {"name": "done", "type": "boolean"}]}]
RELATED = [
    {"name": "Customer", "table": "customers", "fields": [{"name": "name", "type": "string"}, {"name": "email", "type": "email"}]},
    {"name": "Invoice", "table": "invoices", "fields": [
        {"name": "amount", "type": "decimal"}, {"name": "customer_id", "type": "fk", "ref_entity": "Customer"}]},
    {"name": "Payment", "table": "payments", "fields": [
        {"name": "amount", "type": "decimal"}, {"name": "invoice_id", "type": "fk", "ref_entity": "Invoice"}]},
]
LABELS = ["users", "categories", "Project"]   # table names and a class name, as the architecture step lists them
SETS = {"single": ONE, "three_with_relation": RELATED, "table_name_labels": LABELS}


class FakeClient:
    """Counts every model call p04a could make."""
    def __init__(self):
        self.calls = 0

    async def call(self, *a, **k):
        self.calls += 1
        return ""

    generate = chat = complete = call


def build(tmp_path, entities, monkeypatch):
    async def no_smoke(src_dir, emit):  # the phase's smoke test needs a sandbox; the tests below import and run the app
        return {"passed": True, "errors": [], "check_imports": helpers._check_imports(src_dir), "skipped": True}
    monkeypatch.setattr(task_agent, "_smoke_test", no_smoke)
    client = FakeClient()
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda *a, **k: client)
    data = {"project_name": "Demo", "domain": "general", "entities": entities}
    result = asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "app"))
    return result, tmp_path / "app", client


def run_generated_tests(app, entities):
    """One pytest process per entity: the app's rate limiter counts sign-ups per process (5 a minute)."""
    for m in MODS:
        pytest.importorskip(m)
    (app / "tests").mkdir(exist_ok=True)
    failures = []
    for e in normalise_entities(entities, drop_auth_user=True):
        test_file = app / "tests" / f"test_crud_{e['table']}.py"
        test_file.write_text(_generate_crud_tests(app / "src", "Demo", [e]))
        env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z", "ADMIN_EMAIL": "admin@example.com", "SEED_DEMO_DATA": "true",
               "DATABASE_URL": "sqlite+aiosqlite:///" + str(app / f"{e['table']}.db")}
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "asyncio_mode=auto", str(test_file)],
                           cwd=str(app), env=env, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            failures.append(p.stdout[-2000:] + p.stderr[-1000:])
    return failures


@pytest.mark.parametrize("name", list(SETS))
def test_generated_backend_passes_its_generated_crud_tests(name, tmp_path, monkeypatch):
    entities = SETS[name]
    result, app, client = build(tmp_path, entities, monkeypatch)
    assert result.success and client.calls == 0
    assert result.metadata["smoke_test"]["check_imports"] == []
    models = (app / "src" / "models.py").read_text()
    assert models.count("class User(Base)") == 1
    for e in normalise_entities(entities, drop_auth_user=True):
        assert f"class {e['name']}(Base)" in models
    assert run_generated_tests(app, entities) == []


def test_flag_off_keeps_the_old_path(tmp_path, monkeypatch):
    # With the flag off bare labels reach the generators unchanged, as before this change.
    monkeypatch.setenv("CODEGEN_TEMPLATES_FIRST", "0")
    assert not templates_first_enabled()
    result, _, client = build(tmp_path, ONE, monkeypatch)  # dict entities still work on the old path
    assert result.success and client.calls == 0


def test_flag_default_is_on(monkeypatch):
    monkeypatch.delenv("CODEGEN_TEMPLATES_FIRST", raising=False)
    assert templates_first_enabled()


def test_labels_are_normalised_once():
    assert entity_from_label("categories") == {"name": "Category", "table": "categories"}
    assert normalise_entities(["users", "User", {"name": "Task"}, 5, ""]) == [
        {"name": "User", "table": "users"}, {"name": "Task", "table": "tasks"}]
    assert normalise_entities(["users", "Task"], drop_auth_user=True) == [{"name": "Task", "table": "tasks"}]
