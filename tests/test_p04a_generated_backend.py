"""What a customer receives from p04a (KAN-169): the generated backend is built with the real
generators (no model) and must be importable and behave. Each fix to the generator adds a check here.
"""
from __future__ import annotations

import ast
import asyncio
import json
from types import SimpleNamespace

import pytest

from aether_os.phases.p04a_backend_codegen import helpers, task_agent

IR = {
    "domain": "crm", "app_name": "Demo",
    "entities": [
        {"name": "Customer", "table": "customers", "fields": [
            {"name": "name", "type": "string", "nullable": False},
            {"name": "email", "type": "email"},
            {"name": "balance", "type": "decimal"},
            {"name": "status", "type": "enum", "enum_values": ["active", "inactive"]}]},
        {"name": "Invoice", "table": "invoices", "fields": [
            {"name": "amount", "type": "decimal", "nullable": False},
            {"name": "customer_id", "type": "fk", "ref_entity": "Customer"}]}],
    "business_rules": [{"name": "amt_pos", "expression": "amount > 0", "entity": "Invoice"}],
    "permissions": [{"role": "admin", "entity": "Customer", "actions": ["read", "create", "update", "delete"]}],
}


def generate(tmp_path, *, domain="crm", tenancy=False, use_ir=True, monkeypatch=None):
    """Run p04a for a small domain and return the generated app directory."""
    async def no_smoke(src_dir, emit):          # the smoke test needs a sandbox; imports are checked below
        return {"passed": True, "errors": [], "check_imports": helpers._check_imports(src_dir), "skipped": True}
    monkeypatch.setattr(task_agent, "_smoke_test", no_smoke)
    ir = {**IR, "domain": domain}
    (tmp_path / "domain_ir.json").write_text(json.dumps(ir))
    entities = [{"name": e["name"], "table": e["table"],
                 "fields": [{"name": f["name"], "type": f["type"]} for f in e["fields"]]} for e in ir["entities"]]
    data = {"project_name": "Demo", "domain": domain, "entities": entities, "multi_tenancy": tenancy}
    if use_ir:
        data["domain_ir_path"] = str(tmp_path / "domain_ir.json")
    result = asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "app"))
    return result, tmp_path / "app"


@pytest.fixture(params=[("crm", True), ("fintech", True), ("crm", False)],
                ids=["crm-ir", "fintech-ir", "crm-fallback"])
def built(request, tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    domain, use_ir = request.param
    return generate(tmp_path, domain=domain, use_ir=use_ir, monkeypatch=monkeypatch)


def test_generated_app_imports_nothing_from_the_platform(built):
    # The audit service used to import aether_os.core.run_app.child_env; the generated app has no
    # such package, so the phase's own smoke test rejected every run.
    result, app = built
    assert result.metadata["smoke_test"]["check_imports"] == []
    for f in app.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == "aether_os" or n.startswith("aether_os.") for n in names), f"{f}: {names}"
