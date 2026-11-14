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
    env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z", **(env_extra or {})}
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
