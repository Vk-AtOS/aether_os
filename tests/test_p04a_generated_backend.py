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


@pytest.mark.parametrize("domain", ["fintech", "marketplace", "erp", "crm", "healthcare"])
def test_ir_models_and_schemas_compile_for_every_domain(domain):
    # `from decimal import Decimal` was put before `from __future__ import annotations` for money
    # domains, so models.py and schemas.py failed to compile. ast.parse does not catch that; compile does.
    from aether_os.core.domain_ir import DomainIR
    from aether_os.phases.p04a_backend_codegen import ir_generators as g
    ir = DomainIR.load(_write_ir(domain))
    for make in (g.generate_models_py, g.generate_schemas_py):
        compile(make(ir, domain), f"{make.__name__}-{domain}", "exec")


def _write_ir(domain, _cache={}):
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp()) / "domain_ir.json"
    path.write_text(json.dumps({**IR, "domain": domain}))
    return path


# ── running the generated backend (subprocess: it has modules named main, models, auth, database) ──

_RUNNER = r'''
import json, os, sys
app_dir = sys.argv[1]
os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "t.db")
import main
from fastapi.testclient import TestClient
out = {}
with TestClient(main.app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"email": "u1@x.io", "password": "Passw0rd!xyz", "name": "U"})
    out["register"] = r.status_code
    u = {"Authorization": "Bearer " + r.json()["access_token"]}
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
    out["admin_login"] = r.status_code
    a = {"Authorization": "Bearer " + r.json()["access_token"]}
    for ent in sys.argv[2].split(","):
        out[f"user_list_{ent}"] = c.get(f"/api/{ent}", headers=u).status_code
        out[f"user_create_{ent}"] = c.post(f"/api/{ent}", headers=u, json={"name": "A", "amount": 5}).status_code
        out[f"admin_list_{ent}"] = c.get(f"/api/{ent}", headers=a).status_code
        body = {"name": "A", "email": "a@b.io", "status": "active", "balance": 1} if ent == "customers" else {"amount": 5}
        r = c.post(f"/api/{ent}", headers=a, json=body)
        out[f"admin_create_{ent}"] = r.status_code
        rid = r.json().get("id") if r.status_code == 201 else None
        r = c.get(f"/api/{ent}", headers=a)
        out[f"admin_items_{ent}"] = len(r.json().get("items", [])) if r.status_code == 200 else None
        if rid:
            out[f"user_delete_{ent}"] = c.delete(f"/api/{ent}/{rid}", headers=u).status_code
            out[f"admin_delete_{ent}"] = c.delete(f"/api/{ent}/{rid}", headers=a).status_code
print("RESULT " + json.dumps(out))
'''


def run_app(app_dir, entities):
    import os
    import subprocess
    import sys
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    env = {**os.environ, "ADMIN_PASSWORD": "Test-only-Admin-9z", "ENVIRONMENT": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-c", _RUNNER, str(app_dir), entities], capture_output=True, text=True,
                       env=env, timeout=120, cwd=str(app_dir))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"generated app did not run:\n{p.stdout[-800:]}\n{p.stderr[-1500:]}"
    return json.loads(line[7:])


def test_generated_ir_backend_starts_lists_and_enforces_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=True, monkeypatch=monkeypatch)
    r = run_app(app, "customers,invoices")
    assert r["register"] == 201 and r["admin_login"] == 200
    for ent in ("customers", "invoices"):
        # the IR grants admin on Customer and nothing on Invoice: a plain signed-in user gets neither
        assert r[f"user_list_{ent}"] == 403 and r[f"user_create_{ent}"] == 403, (ent, r)
        assert r[f"admin_create_{ent}"] == 201 and r[f"admin_items_{ent}"] >= 1, (ent, r)   # list was a 500
        assert r[f"user_delete_{ent}"] == 403 and r[f"admin_delete_{ent}"] == 204, (ent, r)
        assert r[f"admin_list_{ent}"] == 200, (ent, r)


def test_generated_requirements_cover_what_the_code_imports(built):
    # auth.py builds and loads its RS256 keys with `cryptography`, which was missing from requirements.txt,
    # so a clean install could not import the app.
    _, app = built
    req = (app / "requirements.txt").read_text().lower()
    auth = (app / "src" / "auth.py").read_text()
    assert "cryptography" in auth and "cryptography" in req


def test_generated_postgres_engine_uses_arguments_asyncpg_accepts(built):
    # `connect_args={"options": ...}` is rejected by asyncpg with a TypeError, so the production database
    # (PostgreSQL) never connected; the timeout is passed as a server setting instead.
    import inspect
    asyncpg = pytest.importorskip("asyncpg")
    _, app = built
    db = (app / "src" / "database.py").read_text()
    assert '"options"' not in db and "server_settings" in db
    assert "server_settings" in inspect.signature(asyncpg.connect).parameters


def test_login_rate_limit_cannot_be_bypassed_with_invented_tokens(tmp_path, monkeypatch):
    # The key came from the first characters of whatever Bearer header the caller sent, so every invented
    # token was a fresh bucket (25 bad logins, no 429) and all real users shared one bucket (the JWT header
    # is constant). Login, register and refresh are now limited by source IP only, even when the caller
    # attaches a valid token of their own. Each scenario runs in a fresh app so the buckets start empty.
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=True, monkeypatch=monkeypatch)
    import os
    import subprocess
    import sys
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    runner = r'''
import json, os, secrets, sys
app_dir, mode = sys.argv[1], sys.argv[2]; os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "t.db" + mode)
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    bad = {"email": "nobody@x.io", "password": "bad"}
    if mode == "forged":
        heads = [{"Authorization": "Bearer " + secrets.token_hex(30)} for _ in range(14)]
    else:   # a VALID token of the caller's own for 8 attempts, none for 8 more: one shared limit
        tok = c.post("/api/auth/register", json={"email": "u2@x.io", "password": "Passw0rd!xyz", "name": "U"}).json()["access_token"]
        heads = [{"Authorization": "Bearer " + tok}] * 8 + [{}] * 8
    print("RESULT " + json.dumps([c.post("/api/auth/login", json=bad, headers=h).status_code for h in heads]))
'''
    env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z"}
    for mode in ("forged", "valid_token"):
        p = subprocess.run([sys.executable, "-c", runner, str(app), mode], capture_output=True, text=True, env=env,
                           timeout=120, cwd=str(app))
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
        assert line, p.stderr[-1500:]
        assert 429 in json.loads(line[7:]), (mode, json.loads(line[7:]))     # login allows 10 a minute per source
