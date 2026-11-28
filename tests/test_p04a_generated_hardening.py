"""KAN-169 follow-up: generated-backend hardening. Each test builds the app with the real generators and,
where behaviour matters, starts it in a subprocess (see test_p04a_generated_backend for the method)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from aether_os.core.errors import PipelineBlockedError

from aether_os.tests.test_p04a_generated_backend import IR, generate, run_app

MODS = ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx")


def run_script(app, body: str, env_extra=None, timeout=120):
    """Run `body` inside the generated app (cwd = app dir, src on sys.path, SQLite). It sets `out` (a dict)."""
    for m in MODS:
        pytest.importorskip(m)
    head = ("import json, os, sys\napp_dir = sys.argv[1]; os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, 'src'))\n"
            "os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + os.path.join(app_dir, 't.db')\nout = {}\n")
    env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z", "ADMIN_EMAIL": "admin@example.com", "SEED_DEMO_DATA": "true", **(env_extra or {})}
    p = subprocess.run([sys.executable, "-c", head + body + "\nprint('RESULT ' + json.dumps(out))", str(app)],
                       capture_output=True, text=True, env=env, timeout=timeout, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, p.stdout[-800:] + p.stderr[-1500:]
    return json.loads(line[7:])


@pytest.mark.parametrize("use_ir", [True, False], ids=["ir", "fallback"])
def test_no_permissions_means_the_default_role_model_not_allow_all(tmp_path, monkeypatch, use_ir):
    # Decision D1: an IR / permission model with NO permissions let every signed-in user do everything (a fresh
    # registrant deleted rows). Now: admin everything, member/user read+create+update, delete admin only.
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=use_ir, monkeypatch=monkeypatch, ir_override={**IR, "permissions": []})
    r = run_app(app, "customers,invoices")
    for ent in ("customers", "invoices"):
        assert r[f"user_list_{ent}"] == 200 and r[f"user_create_{ent}"] == 201, (ent, r)
        assert r[f"user_delete_{ent}"] == 403 and r[f"admin_delete_{ent}"] == 204, (ent, r)


def _crm(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("ENVIRONMENT", "test")
    return generate(tmp_path, domain="crm", use_ir=True, monkeypatch=monkeypatch, **kw)[1]


def test_sign_up_policy_is_active_and_bcrypt_limits(tmp_path, monkeypatch):
    # Open self-registration took any password, kept the email case, never looked at is_active (a disabled user
    # logged in and refreshed forever) and a >72-byte password reached bcrypt (ValueError, HTTP 500).
    app = _crm(tmp_path, monkeypatch)
    r = run_script(app, r'''
import main, asyncio
from fastapi.testclient import TestClient
from sqlalchemy import update
with TestClient(main.app, raise_server_exceptions=False) as c:
    reg = lambda e, p: c.post("/api/auth/register", json={"email": e, "password": p, "name": "N"})
    out["short"] = reg("a@x.io", "Short1!").status_code
    out["long"] = reg("b@x.io", "Aa1!" * 19).status_code            # 76 bytes
    ok = reg("MiXed@X.io", "Passw0rd!xyz1")
    out["ok"] = ok.status_code
    out["dup_other_case"] = reg("mixed@x.IO", "Passw0rd!xyz1").status_code
    out["login_other_case"] = c.post("/api/auth/login", json={"email": "MIXED@x.io", "password": "Passw0rd!xyz1"}).status_code
    out["login_long_pw"] = c.post("/api/auth/login", json={"email": "mixed@x.io", "password": "Aa1!" * 40}).status_code
    refresh = ok.json()["refresh_token"]
    from database import AsyncSessionLocal
    from models import User
    async def disable():
        async with AsyncSessionLocal() as db:
            await db.execute(update(User).where(User.email == "mixed@x.io").values(is_active=False)); await db.commit()
    asyncio.run(disable())
    out["login_disabled"] = c.post("/api/auth/login", json={"email": "mixed@x.io", "password": "Passw0rd!xyz1"}).status_code
    out["refresh_disabled"] = c.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code
''')
    assert r["short"] == 422 and r["long"] == 422 and r["ok"] == 201, r
    assert r["dup_other_case"] == 409 and r["login_other_case"] == 200 and r["login_long_pw"] == 401, r
    assert r["login_disabled"] == 401 and r["refresh_disabled"] == 401, r


def test_sign_up_can_be_switched_off(tmp_path, monkeypatch):
    app = _crm(tmp_path, monkeypatch)
    r = run_script(app, r'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    out["register"] = c.post("/api/auth/register", json={"email": "z@x.io", "password": "Passw0rd!xyz1"}).status_code
    out["admin_login"] = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}).status_code
''', env_extra={"ALLOW_SIGNUP": "false"})
    assert r == {"register": 403, "admin_login": 200}


def test_signing_key_is_private_shared_and_not_regenerated(tmp_path, monkeypatch):
    # private_key.pem was written 0644 and each replica generated its own, so tokens failed across replicas.
    app = _crm(tmp_path, monkeypatch)
    keys = tmp_path / "shared" / "k.pem"
    body = r'''
import auth, stat
out["mode"] = oct(stat.S_IMODE(os.stat(os.environ["RSA_PRIVATE_KEY_PATH"]).st_mode))
tok = auth.create_access_token(1, "a@b.io", "admin")
out["tok"] = tok
'''
    env = {"RSA_PRIVATE_KEY_PATH": str(keys), "RSA_PUBLIC_KEY_PATH": str(tmp_path / "shared" / "p.pem")}
    a = run_script(app, body, env)
    b = run_script(app, body.replace("out[\"tok\"] = tok", "import jwt; out['verified'] = jwt.decode(os.environ['T'], auth._PUBLIC_KEY, algorithms=['RS256'])['sub']"),
                   {**env, "T": a["tok"]})
    assert a["mode"] == "0o600" and b["verified"] == "1", (a, b)    # the second process reused the first one's key
    c = run_script(app, "import auth; out['ok'] = auth._PRIVATE_KEY.key_size",
                   {"RSA_PRIVATE_KEY_PATH": str(tmp_path / "none" / "x.pem"), "RSA_PRIVATE_KEY": (keys.read_text()).replace("\n", "\\n")})
    assert c["ok"] == 2048 and not (tmp_path / "none").exists()      # env PEM wins, no file written


def test_response_cache_key_is_full_sha256_dropped_on_writes_and_never_logs_the_url(tmp_path, monkeypatch):
    # The key used the first 8 hex digits of an MD5 of the Authorization header (32 bits), nothing dropped it
    # when the entity was written (stale lists for the whole TTL) and the log line carried the Redis URL
    # (with its password). A fake Redis stands in for the server.
    app = _crm(tmp_path, monkeypatch)
    r = run_script(app, r'''
import types, logging, io, re, asyncio
store = {}
class Fake:
    async def ping(self): return True
    async def get(self, k): return store.get(k)
    async def set(self, k, v, ex=None): store[k] = v
    async def delete(self, *k):
        for x in k: store.pop(x, None)
    async def scan_iter(self, match=None, count=None):
        pre = match.rstrip("*")
        for k in list(store):
            if k.startswith(pre): yield k
aioredis = types.ModuleType("redis.asyncio"); aioredis.from_url = lambda *a, **k: Fake()
sys.modules["redis"] = types.ModuleType("redis"); sys.modules["redis.asyncio"] = aioredis
os.environ["REDIS_URL"] = "redis://:s3cretpw@cache.internal:6379"
buf = io.StringIO(); logging.basicConfig(stream=buf, level=logging.INFO)
from services.cache import RedisCacheMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
api = FastAPI(); api.add_middleware(RedisCacheMiddleware)
calls = {"n": 0}
@api.get("/api/things")
def lst(): calls["n"] += 1; return {"n": calls["n"]}
@api.post("/api/things")
def add(): return {"ok": 1}
c = TestClient(api); h = {"Authorization": "Bearer abc"}
out["first"] = c.get("/api/things", headers=h).json()["n"]
out["cached"] = c.get("/api/things", headers=h).json()["n"]
out["keys"] = [k for k in store]
c.post("/api/things", headers=h)
out["after_write"] = c.get("/api/things", headers=h).json()["n"]
out["logged_password"] = "s3cretpw" in buf.getvalue()
''')
    assert r["first"] == 1 and r["cached"] == 1 and r["after_write"] == 2, r
    assert len(r["keys"][0].rsplit(":", 1)[1]) == 64 and not r["logged_password"], r


def _ir_with(**kw):
    return {**IR, **kw}


def test_business_rule_text_and_names_never_become_code(tmp_path, monkeypatch):
    # A rule expression was pasted into CheckConstraint('<text>') and entity/field names into class and column
    # definitions, so model-written text could run code in the customer's app. Rules outside
    # `column op number|column` are dropped; unsafe names stop the phase.
    evil = "amount > 0'); import os; os.system('touch /tmp/pwned'); ('"
    rules = [{"name": "ok_rule", "expression": "amount > 0", "entity": "Invoice"},
             {"name": "evil", "expression": evil, "entity": "Invoice"},
             {"name": "bad col", "expression": "nosuchcol > 1", "entity": "Invoice"}]
    app = _crm(tmp_path, monkeypatch, ir_override=_ir_with(business_rules=rules))
    models = (app / "src" / "models.py").read_text()
    assert "os.system" not in models and "pwned" not in models
    assert "CheckConstraint('amount > 0'" in models and "nosuchcol" not in models
    compile(models, "models.py", "exec")
    monkeypatch.setenv("ENVIRONMENT", "test")
    bad = _ir_with(entities=[{**IR["entities"][0], "name": "Customer'); import os #"}, IR["entities"][1]])
    (tmp_path / "x").mkdir()
    with pytest.raises(PipelineBlockedError, match="unsafe_name"):
        generate(tmp_path / "x", domain="crm", use_ir=True, monkeypatch=monkeypatch, ir_override=bad)


def test_foreign_key_cycles_in_the_ir_are_found():
    # The cycle check only read legacy "ForeignKey('t.id')" type strings, never the IR's type "fk", so it never fired.
    from aether_os.phases.p04a_backend_codegen.pre_gen_validator import run_pre_gen_checks
    def ent(n, ref, nullable):
        return {"name": n, "table": n.lower() + "s", "fields": [{"name": "x_id", "type": "fk", "ref_entity": ref, "nullable": nullable}]}
    hard = run_pre_gen_checks({"entities": [ent("A", "B", False), ent("B", "A", False)]})
    soft = run_pre_gen_checks({"entities": [ent("A", "B", True), ent("B", "A", False)]})
    assert not hard.passed and "a -> b -> a" in hard.errors[0]
    assert soft.passed and any("circular_fk_nullable" in w for w in soft.warnings)


def test_project_name_cannot_inject_code_into_the_generated_app(tmp_path, monkeypatch):
    # {PROJECT_NAME} was substituted into main.py strings and a docstring, the seed prefix, the Makefile and the
    # README, so a name containing triple quotes and a newline ran as code in the customer's app.
    monkeypatch.setenv("ENVIRONMENT", "test")
    import asyncio
    from types import SimpleNamespace
    from aether_os.phases.p04a_backend_codegen import task_agent
    from aether_os.tests.test_p04a_generated_backend import helpers
    async def no_smoke(src_dir, emit):
        return {"passed": True, "errors": [], "check_imports": helpers._check_imports(src_dir), "skipped": True}
    monkeypatch.setattr(task_agent, "_smoke_test", no_smoke)
    evil = 'X"""\nimport os; os.system("touch /tmp/pwned_a6b")\n# $(shell id) {{x}}'
    (tmp_path / "ir.json").write_text(json.dumps(IR))
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_name": evil, "domain": "crm", "entities": [],
                               "domain_ir_path": str(tmp_path / "ir.json")}), [], tmp_path / "app"))
    app = tmp_path / "app"
    import ast
    for f in list(app.rglob("*.py")):
        calls = [n for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "system"]
        assert not calls, f
    assert "$(" not in (app / "Makefile").read_text()


def test_production_hardening_of_the_generated_main(tmp_path, monkeypatch):
    # /ready returned str(exception) (DB host, user), /docs and /openapi.json were public in production, an
    # integrity error was a 500, the Dockerfile ran as root.
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = generate(tmp_path, domain="crm", use_ir=False, monkeypatch=monkeypatch)[1]
    docker = (app / "Dockerfile").read_text()
    assert "USER app" in docker and "HEALTHCHECK" in docker
    body = r'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    out["docs"] = [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")]
    import database
    class Down:
        def connect(self): raise RuntimeError("password authentication failed for user dbadmin at 10.9.8.7")
    database.engine = Down()
    r = c.get("/ready"); out["ready"] = [r.status_code, r.text]
    adm = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}).json()["access_token"]
    out["missing_required"] = c.post("/api/customers", headers={"Authorization": "Bearer " + adm}, json={"name": "A"}).status_code
'''
    # production never creates tables (KAN-267): the database must be migrated before the app starts
    import asyncio
    from aether_os.phases.p04a_backend_codegen.templates_alembic import generate_initial_migration
    monkeypatch.setenv("AETHER_SANDBOX", "none")
    monkeypatch.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    asyncio.run(generate_initial_migration(app))
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=app, capture_output=True, text=True,
                        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{app}/t.db"}, timeout=120)
    assert up.returncode == 0, up.stderr[-1500:]
    prod = run_script(app, body, {"ENVIRONMENT": "production"})
    assert prod["docs"] == [404, 404, 404], prod
    assert prod["ready"][0] == 503 and "dbadmin" not in prod["ready"][1] and "10.9.8.7" not in prod["ready"][1], prod
    assert prod["missing_required"] == 409, prod
    dev = run_script(app, body, {"ENVIRONMENT": "development"})
    assert dev["docs"] == [200, 200, 200], dev
    on = run_script(app, body, {"ENVIRONMENT": "production", "ENABLE_DOCS": "true"})
    assert on["docs"] == [200, 200, 200], on


def test_alembic_env_sees_the_apps_tables(tmp_path, monkeypatch):
    # env.py imported `src.database`, a second copy of the module with its own empty Base: autogenerate saw no
    # tables (and `make migrate` imported the models twice).
    pytest.importorskip("alembic")
    app = _crm(tmp_path, monkeypatch)
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{app}/mig.db"}
    p = subprocess.run([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "init"], cwd=app, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    rev = next((app / "alembic" / "versions").glob("*.py")).read_text()
    assert "create_table('customers'" in rev and "create_table('invoices'" in rev, rev[:600]


@pytest.mark.parametrize("domain", ["fintech", "healthcare"])
def test_pipelines_are_generated_gated_and_never_report_success_for_stubs(tmp_path, monkeypatch, domain):
    # generate_pipeline_code read step.service_required, which the ProcessStep class that is actually in use
    # does not have: AttributeError, no pipelines for fintech and healthcare. The trigger routes then answered 202
    # to any signed-in user while the stub service "succeeded" without doing anything.
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = generate(tmp_path, domain=domain, use_ir=True, monkeypatch=monkeypatch)[1]
    router = (app / "src" / "routers" / "pipeline_events.py")
    assert router.exists(), "pipeline generation failed"
    import re
    path = "/api/pipeline-events/" + re.search(r'@router.post\("/([^"]+)"\)', router.read_text()).group(1)
    r = run_script(app, f'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    h = lambda t: {{"Authorization": "Bearer " + t}}
    user = c.post("/api/auth/register", json={{"email": "p@x.io", "password": "Passw0rd!xyz1"}}).json()["access_token"]
    adm = c.post("/api/auth/login", json={{"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}}).json()["access_token"]
    out["anon"] = c.post("{path}", json={{}}).status_code
    out["user"] = c.post("{path}", json={{}}, headers=h(user)).status_code
    out["admin"] = c.post("{path}", json={{}}, headers=h(adm)).status_code
''')
    assert r == {"anon": 401, "user": 403, "admin": 501}, r


def test_role_names_and_feature_text_cannot_inject_code(tmp_path):
    # Role names went into `NAME = "<role>"`, the CRUD guards and the PERMISSIONS dict (as JSON text); feature
    # and project names went into comments. A quote or a newline in any of them became code in the customer's app.
    import ast
    from aether_os.phases.p04a_backend_codegen.crud_generator import _fallback_crud_routers
    from aether_os.phases.p04a_backend_codegen.helpers_permissions import _generate_permissions_service
    from aether_os.phases.p04a_backend_codegen.helpers_sse import _generate_sse_router
    evil = 'Boss"\nimport os; os.system("x")  #'
    pm = {"roles": [evil, "Admin"], "permissions": {evil: {"Customer": ["read"]}}, "row_filters": {"a": evil}}
    _generate_permissions_service(tmp_path, pm)
    crud = _fallback_crud_routers([{"name": "Customer", "table": "customers", "fields": [{"name": "name", "type": "string"}]}],
                                  permission_model=pm)
    sse = _generate_sse_router(["live\nimport os; os.system('y')"], "P\nimport os; os.system('z')")
    for label, code in (("permissions", (tmp_path / "services" / "permissions.py").read_text()), ("crud", crud), ("sse", sse)):
        calls = [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "system"]
        assert not calls, label


def test_gate_fails_on_missing_files_and_broken_code(tmp_path, monkeypatch):
    # validate() only ever appended to `warnings`: every non-empty output directory passed.
    from aether_os.phases.base import TaskResult
    from aether_os.phases.p04a_backend_codegen import gate
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=True, monkeypatch=monkeypatch)
    ok = gate.validate(TaskResult(output_path=str(app), confidence=1.0, confidence_reason="", metadata={}, success=True))
    assert ok.passed, ok.issues
    (app / "src" / "models.py").write_text("class X(:\n")
    (app / "src" / "seed.py").unlink()
    (app / "src" / "extra.py").write_text("from aether_os.core import x\n")
    bad = gate.validate(TaskResult(output_path=str(app), confidence=1.0, confidence_reason="", metadata={}, success=True))
    assert not bad.passed
    text = " ".join(bad.issues)
    assert "models.py does not compile" in text and "seed.py is missing" in text and "extra.py imports" in text


def test_fallback_generator_isolates_tenants_too(tmp_path, monkeypatch):
    # The IR path had org_id columns; the fallback generator's CRUD filtered on models.X.org_id but its models and seed
    # had no such column (AttributeError on the first request).
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = generate(tmp_path, domain="crm", tenancy=True, use_ir=False, monkeypatch=monkeypatch)[1]
    assert "org_id" in (app / "src" / "models.py").read_text()
    r = run_script(app, r'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    tok = lambda r: {"Authorization": "Bearer " + r.json()["access_token"]}
    admin = tok(c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}))
    out["admin_list"] = c.get("/api/customers", headers=admin).status_code
    out["admin_sees"] = len(c.get("/api/customers", headers=admin).json().get("items", []))
    r = c.post("/api/customers", headers=admin, json={"name": "Mine", "email": "m@x.io", "status": "active"}); out["create"] = r.status_code
    mine = r.json().get("id")
    import asyncio
    from sqlalchemy import update
    from database import AsyncSessionLocal
    from models import User
    reg = c.post("/api/auth/register", json={"email": "t2@x.io", "password": "Passw0rd!xyz1"}); out["register"] = reg.status_code
    async def promote():
        async with AsyncSessionLocal() as db:
            await db.execute(update(User).where(User.email == "t2@x.io").values(role="admin")); await db.commit()
    asyncio.run(promote())
    t2 = tok(c.post("/api/auth/login", json={"email": "t2@x.io", "password": "Passw0rd!xyz1"}))
    out["t2_sees"] = len(c.get("/api/customers", headers=t2).json().get("items", []))
    out["t2_reads_mine"] = c.get(f"/api/customers/{mine}", headers=t2).status_code
''')
    assert r["admin_list"] == 200 and r["create"] == 201 and r["admin_sees"] >= 2 and r["register"] == 201, r
    assert r["t2_sees"] == 0 and r["t2_reads_mine"] == 404, r


def test_ir_seed_uses_real_foreign_keys_and_unique_strings(tmp_path, monkeypatch):
    # The seed wrote customer_id = (row % 3) + 1 whether or not such a parent existed (a foreign-key violation on
    # PostgreSQL; SQLite does not enforce it unless asked) and gave a UNIQUE string column the same value from row 11
    # on (ten-entry value lists, twenty rows). Foreign keys are enforced here with PRAGMA foreign_keys=ON.
    ents = [{"name": "Customer", "table": "customers", "fields": [
                {"name": "name", "type": "string", "nullable": False},
                {"name": "code", "type": "string", "unique": True}]},
            {"name": "Task", "table": "tasks", "fields": [
                {"name": "title", "type": "string"},
                {"name": "customer_id", "type": "fk", "ref_entity": "Customer"},
                {"name": "owner_id", "type": "fk", "ref_entity": "User"},
                {"name": "parent_id", "type": "fk", "ref_entity": "Task"}]}]
    app = _crm(tmp_path, monkeypatch, ir_override=_ir_with(entities=ents, business_rules=[], permissions=[]))
    r = run_script(app, r'''
from sqlalchemy import event, text
import database
@event.listens_for(database.engine.sync_engine, "connect")
def _fk_on(conn, _rec): conn.execute("PRAGMA foreign_keys=ON")
import main, asyncio
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    async def count():
        async with database.AsyncSessionLocal() as db:
            n = (await db.execute(text("select count(*), count(distinct code) from customers"))).one()
            t = (await db.execute(text("select count(*), count(owner_id), count(customer_id), count(parent_id) from tasks"))).one()
            return list(n) + list(t)
    out["counts"] = asyncio.run(count())
''')
    assert r["counts"] == [20, 20, 20, 20, 20, 0], r


@pytest.mark.parametrize("use_ir", [True, False], ids=["ir", "fallback"])
def test_list_endpoints_take_page_size_up_to_200_in_both_generators(tmp_path, monkeypatch, use_ir):
    # The frontend sends page and page_size (<=200). The IR backend named it `limit` and capped it at 100 (page_size
    # was silently ignored: always 20 rows); the fallback already took page_size <= 200.
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = generate(tmp_path, domain="crm", use_ir=use_ir, monkeypatch=monkeypatch)[1]
    r = run_script(app, r'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]}).json()["access_token"]}
    for i in range(3): c.post("/api/customers", headers=h, json={"name": f"C{i}", "email": f"c{i}@x.io", "status": "active"})
    ok = c.get("/api/customers?page=1&page_size=200", headers=h)
    out["ok"] = ok.status_code
    out["size"] = ok.json().get("page_size")
    out["small"] = len(c.get("/api/customers?page=1&page_size=2", headers=h).json()["items"])
    out["too_big"] = c.get("/api/customers?page_size=201", headers=h).status_code
''')
    assert r["ok"] == 200 and r["size"] == 200 and r["small"] == 2 and r["too_big"] == 422, r


def test_user_entity_and_tenant_fields_are_never_client_writable(tmp_path, monkeypatch):
    # KAN-69 G1/G2: a spec entity named User got a CRUD router whose schemas carried role and password_hash,
    # so a signed-up user PATCHed itself to admin; org_id could be mass-assigned across tenants.
    ir = {**IR, "entities": IR["entities"] + [
        {"name": "User", "table": "users", "fields": [
            {"name": "email", "type": "email"}, {"name": "role", "type": "string"},
            {"name": "password_hash", "type": "string"}]},
        {"name": "Note", "table": "notes", "fields": [
            {"name": "body", "type": "string"}, {"name": "org_id", "type": "string"},
            {"name": "password_hash", "type": "string"}]}]}
    from aether_os.core.domain_ir import DomainIR
    from aether_os.phases.p04a_backend_codegen import ir_generators as g
    import tempfile
    import pathlib
    path = pathlib.Path(tempfile.mkdtemp()) / "domain_ir.json"
    path.write_text(json.dumps(ir))
    d = DomainIR.load(path)
    schemas = g.ir_to_schemas(d, "crm", multi_tenancy=True)
    crud = g.generate_crud_py(d, multi_tenancy=True)
    models = g.ir_to_models(d, "crm", multi_tenancy=True)
    assert "UserCreate" not in schemas and "UserUpdate" not in schemas and "users_router" not in crud
    assert "role:" not in schemas and "password_hash" not in schemas and "org_id" not in schemas
    assert models.count("org_id = Column") == 4          # users + three entities, no duplicate column
    compile(models, "m", "exec"); compile(schemas, "s", "exec"); compile(crud, "c", "exec")
    run = _crm(tmp_path, monkeypatch, ir_override=ir, tenancy=True)
    assert "users_router" not in (run / "src/routers/crud.py").read_text()


def test_refresh_token_is_an_httponly_cookie_and_logout_clears_it(tmp_path, monkeypatch):
    # KAN-69 G10: the browser kept the 7-day refresh token in localStorage. The API now also sets it as an
    # HttpOnly SameSite=Strict cookie on /api/auth, refresh works from the cookie alone, logout clears it.
    app = _crm(tmp_path, monkeypatch)
    r = run_script(app, r'''
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=False) as c:
    reg = c.post("/api/auth/register", json={"email": "ck@x.io", "password": "Passw0rd!xyz1", "name": "N"})
    out["register"] = reg.status_code
    cookie = reg.headers.get("set-cookie", "").lower()
    out["flags"] = [f in cookie for f in ("refresh_token=", "httponly", "samesite=strict", "path=/api/auth")]
    out["refresh_from_cookie"] = c.post("/api/auth/refresh").status_code          # no body: the cookie client sends it
    out["refresh_from_body"] = c.post("/api/auth/refresh", json={"refresh_token": reg.json()["refresh_token"]}).status_code
    out["logout"] = c.post("/api/auth/logout").status_code
    c.cookies.clear()
    out["refresh_without_anything"] = c.post("/api/auth/refresh").status_code
''')
    assert r == {"register": 201, "flags": [True] * 4, "refresh_from_cookie": 200, "refresh_from_body": 200,
                 "logout": 204, "refresh_without_anything": 401}, r
