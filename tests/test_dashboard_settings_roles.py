"""KAN-121: org-wide settings need owner/admin on the server (D7)."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import aether_os.core.db as db
from aether_os.core.models import Organisation
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import account_settings_router, settings_advanced_router


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[Organisation.__table__]))
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o1", name="Old", slug="old"))
        await s.commit()
    who = {"user": {"user_id": "u", "org_id": "o1", "role": "member"}}
    app = FastAPI()
    app.include_router(account_settings_router.router)
    app.include_router(settings_advanced_router.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.who = who
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "viewer", "user"])
async def test_non_admin_cannot_change_org_settings_or_stage_config(client, role):
    client.who["user"]["role"] = role
    r = await client.post("/account/settings", json={"autonomous_mode": True})
    assert r.status_code == 403
    r = await client.post("/settings/phases/p01/config", json={"enabled": False, "priority": "normal"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_rename_org_and_unknown_fields_are_rejected(client):
    client.who["user"]["role"] = "admin"
    r = await client.post("/account/settings", json={"org_name": "New", "autonomous_mode": True})
    assert r.status_code == 200, r.text
    assert (await client.get("/account/settings")).json()["name"] == "New"
    for bad in ({"decision_mode": "x"}, {"notification_prefs": {}}):
        assert (await client.post("/account/settings", json=bad)).status_code == 400
    assert (await client.post("/account/settings", json={"autonomous_mode": "yes"})).status_code == 422
