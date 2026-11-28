"""KAN-109/100: s10 copies the enterprise packages into the app and wires them; a generated app serves them with auth."""
import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from aether_os.phases.p12a_feature_flags import task_agent as p12a
from aether_os.phases.p12b_ab_testing import task_agent as p12b
from aether_os.phases.p18_billing_metering import task_agent as p18
from aether_os.stages.s10_enterprise.supervisor import _autowire_enterprise_extensions
from aether_os.tests.test_p04a_generated_backend import IR, generate

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
    u = {"Authorization": "Bearer " + r.json()["access_token"]}
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
    a = {"Authorization": "Bearer " + r.json()["access_token"]}
    out["ab_anon"] = c.get("/api/experiments/").status_code
    out["ab_user_list"] = c.get("/api/experiments/", headers=u).status_code
    body = {"name": "x", "variants": ["a", "b"]}
    out["ab_user_create"] = c.post("/api/experiments/", headers=u, json=body).status_code
    out["ab_admin_create"] = c.post("/api/experiments/", headers=a, json=body).status_code
    out["flags_anon"] = c.get("/api/flags/").status_code
    out["flags_user"] = c.get("/api/flags/", headers=u).status_code
    out["flags_admin"] = c.get("/api/flags/", headers=a).status_code
    out["billing_unset_secret"] = c.post("/api/billing/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "x"}).status_code
    # KAN-109: the metering middleware is mounted only when OPENMETER_URL is set, and then meters entity calls
    out["metering_mounted"] = any(m.cls.__name__ == "MeteringMiddleware" for m in main.app.user_middleware)
    if out["metering_mounted"]:
        import asyncio, sys as _sys
        mw = _sys.modules["billing.metering_middleware"]
        sent = []
        async def fake_post(entity, tenant_id):
            sent.append(entity)
        mw._post_metering_event = fake_post
        path = mw.METERED_PREFIXES[0]
        out["metered_status"] = c.get(path, headers=a).status_code
        c.get("/api/experiments/", headers=a)                      # not an entity path: not metered
        out["metered"] = sent == [path.rsplit("/", 1)[-1]]
print("RESULT " + json.dumps(out))
'''


def test_enterprise_extensions_are_copied_into_the_app_wired_and_authenticated(tmp_path, monkeypatch):
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx", "stripe"):
        pytest.importorskip(mod)
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, monkeypatch=monkeypatch)
    src = app / "src"
    dirs = {n: tmp_path / "phase" / n for n in ("p12a_feature_flags", "p12b_ab_testing", "p18_billing_metering")}
    for name, mod in (("p12a_feature_flags", p12a), ("p12b_ab_testing", p12b), ("p18_billing_metering", p18)):
        dirs[name].mkdir(parents=True)
        asyncio.run(mod.run(SimpleNamespace(input_data={"entities": [], "domain_ir": IR}), [], dirs[name]))
    wired = _autowire_enterprise_extensions(src, list(dirs) + ["p16_iam"], dirs)
    assert sorted(wired) == ["ab_testing", "billing", "billing.metering_middleware", "feature_flags"]
    assert _autowire_enterprise_extensions(src, list(dirs), dirs) == wired            # idempotent
    assert (src / "main.py").read_text().count("auto-wired by s10") == 4
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    env = {**os.environ, "ADMIN_PASSWORD": "Test-only-Admin-9z", "ADMIN_EMAIL": "admin@example.com", "SEED_DEMO_DATA": "true", "ENVIRONMENT": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("STRIPE_WEBHOOK_SECRET", None)
    env.pop("OPENMETER_URL", None)

    def run_app(extra_env):
        p = subprocess.run([sys.executable, "-c", _RUNNER, str(app)], capture_output=True, text=True,
                           env={**env, **extra_env}, timeout=120, cwd=str(app))
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
        assert line, f"app did not run:\n{p.stdout[-800:]}\n{p.stderr[-1500:]}"
        return json.loads(line[7:])

    routes = {
        "ab_anon": 401, "ab_user_list": 200, "ab_user_create": 403, "ab_admin_create": 200,
        "flags_anon": 401, "flags_user": 403, "flags_admin": 200, "billing_unset_secret": 503,
    }
    assert run_app({}) == {**routes, "metering_mounted": False}        # no OpenMeter configured: not mounted
    (app / "t.db").unlink()
    assert run_app({"OPENMETER_URL": "http://openmeter.invalid:8888"}) == {
        **routes, "metering_mounted": True, "metered_status": 200, "metered": True}
