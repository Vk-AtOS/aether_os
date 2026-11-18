"""Generated apps fail closed: no built-in database URL/password, no webhook accepted without a signing secret."""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import time
import types

import pytest

from aether_os.phases.p03_scaffolding.task_agent import create_minimal_scaffold
from aether_os.phases.p04a_backend_codegen.templates import _CONFIG_PY, _DATABASE_PY
from aether_os.phases.p04b_business_logic.logic_generators import generate_stripe_service
from aether_os.phases.p04c_integration_codegen.templates.stripe import generate_stripe_client


def _forged():
    """An event signed with the EMPTY key: what anyone can produce when the secret is unset."""
    body = json.dumps({"id": "evt_1", "object": "event", "type": "invoice.payment_succeeded",
                       "data": {"object": {"customer": "cus_1"}}})
    ts = str(int(time.time()))
    sig = hmac.new(b"", f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body.encode(), f"t={ts},v1={sig}"


def _load(tmp_path, name, src):
    f = tmp_path / f"{name}.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_database_module_refuses_to_start_without_database_url(monkeypatch):
    pytest.importorskip("aiosqlite")
    assert "postgres:postgres" not in _DATABASE_PY and "sqlite" not in _CONFIG_PY.split("database_url")[1].split("\n")[0]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        exec(compile(_DATABASE_PY, "database.py", "exec"), {"__name__": "database"})
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    ns = {"__name__": "database"}
    exec(compile(_DATABASE_PY, "database.py", "exec"), ns)
    assert ns["DATABASE_URL"] == "sqlite+aiosqlite:///./x.db"


def test_scaffold_compose_has_no_fixed_database_password(tmp_path):
    out = create_minimal_scaffold("Demo", {"backend": "fastapi"}, tmp_path)
    compose = (out / "docker-compose.yml").read_text()
    assert "apppass" not in compose and compose.count("${POSTGRES_PASSWORD:?") == 2


@pytest.mark.parametrize("make", [generate_stripe_service, generate_stripe_client], ids=["p04b", "p04c"])
def test_generated_stripe_services_refuse_webhooks_when_the_secret_is_unset(make, tmp_path, monkeypatch):
    pytest.importorskip("stripe")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    mod = _load(tmp_path, "stripe_gen_" + make.__name__, make())
    svc = mod.StripeService() if hasattr(mod, "StripeService") else mod.StripeClient()
    body, sig = _forged()
    with pytest.raises(Exception, match="STRIPE_WEBHOOK_SECRET is not set"):
        asyncio.run(svc.handle_webhook(body, sig))


def test_generated_billing_webhook_answers_503_when_the_secret_is_unset(tmp_path, monkeypatch):
    pytest.importorskip("stripe")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import declarative_base

    from aether_os.phases.p18_billing_metering.metering_generator import generate_stripe_webhook_handler
    db = types.ModuleType("database")
    db.Base, db.AsyncSessionLocal = declarative_base(), None
    auth = types.ModuleType("auth")
    auth.get_current_user = lambda: {}
    monkeypatch.setitem(sys.modules, "database", db)
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    mod = _load(tmp_path, "billing_webhook_unset", generate_stripe_webhook_handler("demo"))
    app = FastAPI()
    app.include_router(mod.billing_router)
    body, sig = _forged()
    assert TestClient(app).post("/billing/stripe/webhook", content=body, headers={"Stripe-Signature": sig}).status_code == 503


def test_billing_webhook_table_is_on_the_apps_own_base(tmp_path, monkeypatch):
    # Launched as "uvicorn src.main:app" both "database" and "src.database" import; main.py creates the
    # tables of database.Base, so the billing model must be registered there, not on a second copy.
    pytest.importorskip("stripe")
    from sqlalchemy.orm import declarative_base

    from aether_os.phases.p18_billing_metering.metering_generator import generate_stripe_webhook_handler
    mods = {}
    for name in ("database", "src.database"):
        m = types.ModuleType(name)
        m.Base, m.AsyncSessionLocal = declarative_base(), None
        mods[name] = m
    auth = types.ModuleType("auth")
    auth.get_current_user = lambda: {}
    src = types.ModuleType("src")
    src.database = mods["src.database"]
    for name, m in {**mods, "auth": auth, "src": src, "src.auth": auth}.items():
        monkeypatch.setitem(sys.modules, name, m)
    _load(tmp_path, "billing_webhook_base", generate_stripe_webhook_handler("demo"))
    assert "billing_accounts" in mods["database"].Base.metadata.tables
    assert "billing_accounts" not in mods["src.database"].Base.metadata.tables


def test_p04a_has_no_bare_phases_imports():
    # "from phases.x" only works when the repo root happens to be on sys.path, and then loads every
    # module twice (as phases.x and aether_os.phases.x), splitting module state.
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "phases" / "p04a_backend_codegen"
    bad = [f"{f.name}:{n.lineno}" for f in root.glob("*.py") for n in ast.walk(ast.parse(f.read_text()))
           if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "phases"]
    assert not bad, bad
