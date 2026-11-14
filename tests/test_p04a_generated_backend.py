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


def generate(tmp_path, *, domain="crm", tenancy=False, use_ir=True, monkeypatch=None, permission_model=None):
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
    if permission_model:
        data["permission_model"] = permission_model
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


def test_generated_app_ships_no_known_admin_password_or_real_secret_in_the_example(built):
    # Every generated app seeded admin@example.com with the same default password, wrote it into
    # .env.example next to the app's real SECRET_KEY, and logged it at startup.
    _, app = built
    everything = {f: f.read_text(errors="replace") for f in app.rglob("*") if f.is_file() and f.suffix in
                  (".py", ".md", ".txt", ".example", "", ".yml", ".yaml") and f.name != "private_key.pem"}
    assert not [f.name for f, t in everything.items() if "Admin1234" in t]
    example = (app / ".env.example").read_text()
    real = dict(ln.split("=", 1) for ln in (app / ".env").read_text().splitlines() if "=" in ln and not ln.startswith("#"))
    assert real["SECRET_KEY"] not in example and real["ADMIN_PASSWORD"] not in example
    assert "SECRET_KEY=change-me" in example and "ADMIN_PASSWORD=change-me" in example
    for name in (".gitignore", ".dockerignore"):
        assert ".env" in (app / name).read_text().splitlines()


@pytest.mark.parametrize("source", ["dotenv", "private_file"])
def test_seed_admin_password_is_random_and_never_the_old_default(tmp_path, monkeypatch, source):
    # "dotenv": the generated .env carries this app's own random ADMIN_PASSWORD.
    # "private_file": no .env and no ADMIN_PASSWORD, so the seed writes a random one to a 0600 file.
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=True, monkeypatch=monkeypatch)
    import os
    import subprocess
    import sys
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    expected = dict(ln.split("=", 1) for ln in (app / ".env").read_text().splitlines()
                    if "=" in ln and not ln.startswith("#"))["ADMIN_PASSWORD"]
    if source == "private_file":
        (app / ".env").unlink()
    runner = r'''
import json, os, sys
app_dir = sys.argv[1]; os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "seedtest.db")
import logging; logging.basicConfig(level=logging.INFO)
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    f = os.path.join(app_dir, "admin_initial_password.txt")
    pw = open(f).read() if os.path.exists(f) else sys.argv[2]
    ok = c.post("/api/auth/login", json={"email": "admin@example.com", "password": pw}).status_code
    old = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "Admin1234!"}).status_code
    mode = oct(os.stat(f).st_mode & 0o777) if os.path.exists(f) else None
print("RESULT " + json.dumps({"ok": ok, "old": old, "mode": mode, "pw": pw}))
'''
    env = {k: v for k, v in os.environ.items() if k != "ADMIN_PASSWORD"}
    env["ENVIRONMENT"] = "test"
    p = subprocess.run([sys.executable, "-c", runner, str(app), expected], capture_output=True, text=True, env=env,
                       timeout=120, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, p.stderr[-1500:]
    r = json.loads(line[7:])
    assert r["ok"] == 200 and r["old"] == 401 and len(r["pw"]) >= 16
    assert r["mode"] == ("0o600" if source == "private_file" else None)
    assert r["pw"] not in p.stdout.replace(line, "") and r["pw"] not in p.stderr     # never logged


def test_multi_tenant_backend_isolates_organisations(tmp_path, monkeypatch):
    # With multi_tenancy on, no model had an org_id column, so every filtered call raised AttributeError
    # and the seed failed. Each entity row and each user now carries a tenant; signing up starts a new one.
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", tenancy=True, use_ir=True, monkeypatch=monkeypatch)
    import os
    import subprocess
    import sys
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    assert "org_id" in (app / "src" / "models.py").read_text()
    runner = r'''
import json, os, sys
app_dir = sys.argv[1]; os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "mt.db")
import main
from fastapi.testclient import TestClient
out = {}
with TestClient(main.app, raise_server_exceptions=False) as c:
    tok = lambda r: {"Authorization": "Bearer " + r.json()["access_token"]}
    admin = tok(c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}))
    out["admin_list"] = c.get("/api/customers", headers=admin).status_code
    out["admin_sees_seed"] = len(c.get("/api/customers?limit=100", headers=admin).json().get("items", []))
    r = c.post("/api/customers", headers=admin, json={"name": "Mine", "email": "m@x.io", "status": "active", "balance": 1})
    out["admin_create"] = r.status_code
    mine = r.json().get("id")
    # a second tenant: sign up, the new user is not an admin, so promote it in the database to compare tenants
    reg = c.post("/api/auth/register", json={"email": "t2@x.io", "password": "Passw0rd!xyz", "name": "T2"})
    out["register"] = reg.status_code
    import asyncio
    from sqlalchemy import update
    from database import AsyncSessionLocal
    from models import User
    async def promote():
        async with AsyncSessionLocal() as db:
            await db.execute(update(User).where(User.email == "t2@x.io").values(role="admin")); await db.commit()
    asyncio.run(promote())
    t2 = tok(c.post("/api/auth/login", json={"email": "t2@x.io", "password": "Passw0rd!xyz"}))
    out["t2_sees"] = len(c.get("/api/customers?limit=100", headers=t2).json().get("items", []))
    out["t2_reads_mine"] = c.get(f"/api/customers/{mine}", headers=t2).status_code
    out["t2_deletes_mine"] = c.delete(f"/api/customers/{mine}", headers=t2).status_code
    out["admin_still_has_mine"] = c.get(f"/api/customers/{mine}", headers=admin).status_code
    out["admin_stats"] = c.get("/api/stats", headers=admin).json().get("total_customers")
    out["t2_stats"] = c.get("/api/stats", headers=t2).json().get("total_customers")      # was: every tenant's count
print("RESULT " + json.dumps(out))
'''
    env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z"}
    p = subprocess.run([sys.executable, "-c", runner, str(app)], capture_output=True, text=True, env=env, timeout=120, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, p.stdout[-600:] + p.stderr[-1500:]
    r = json.loads(line[7:])
    assert r["admin_list"] == 200 and r["admin_create"] == 201 and r["admin_sees_seed"] >= 2, r
    assert r["register"] == 201 and r["t2_sees"] == 0, r              # the new tenant sees none of tenant "default"
    assert r["t2_reads_mine"] == 404 and r["t2_deletes_mine"] == 404 and r["admin_still_has_mine"] == 200, r
    assert r["admin_stats"] >= 2 and r["t2_stats"] == 0, r          # /stats counts only the caller's tenant


def test_fallback_backend_denies_by_default_and_ignores_role_name_case(tmp_path, monkeypatch):
    # Fallback generator: `_get_roles_for_action` returned None ("any signed-in user") whenever no role
    # covered an action, and require_role/require_admin compared role names case-sensitively. The model here
    # grants only Customer read to "Manager" and nothing on Invoice; a plain user must get nothing, the seeded
    # admin everything, and a role written "ADMIN" must still be admin.
    monkeypatch.setenv("ENVIRONMENT", "test")
    pm = {"roles": ["Manager"], "permissions": {"Manager": {"Customer": ["read"]}}}
    _, app = generate(tmp_path, domain="crm", use_ir=False, monkeypatch=monkeypatch, permission_model=pm)
    r = run_app(app, "customers,invoices")
    assert r["register"] == 201 and r["admin_login"] == 200, r
    for ent in ("customers", "invoices"):
        assert r[f"user_list_{ent}"] == 403 and r[f"user_create_{ent}"] == 403, (ent, r)
        assert r[f"admin_create_{ent}"] == 201 and r[f"admin_list_{ent}"] == 200, (ent, r)
        assert r[f"user_delete_{ent}"] == 403 and r[f"admin_delete_{ent}"] == 204, (ent, r)
    guard = (app / "src" / "auth.py").read_text()
    assert "lower()" in guard.split("def require_role")[1]


def test_fallback_single_item_cache_is_per_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", tenancy=True, use_ir=False, monkeypatch=monkeypatch)
    crud = "".join(p.read_text() for p in (app / "src" / "routers").glob("*.py"))
    # list keys already carry the org; the single-item key must too (tenant B read tenant A's cached row)
    assert "current_user.get('org_id', '')}:{item_id}" in crud, "single-item cache key is not tenant-scoped"
    # writes must drop the very key the read path uses (a different key left updated or deleted rows cached)
    reads = crud.count("_ck = f\"Customer:{current_user.get('org_id', '')}:{item_id}\"")
    deletes = crud.count("_cache_delete(f\"Customer:{current_user.get('org_id', '')}:{item_id}\")")
    assert reads == 1 and deletes == 2, (reads, deletes)
    assert '_cache_delete(f"Customer:{item_id}")' not in crud
