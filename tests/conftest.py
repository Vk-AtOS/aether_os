"""Shared fixture for the gateway hardening tests (test_refresh_rotation, test_scim_auth,
test_portal_auth, test_saml_relay_state, test_provider_test_endpoint, test_prune_artifacts).

Same approach as test_security_fixes.py: the real FastAPI app through TestClient, a
throwaway SQLite database, real registered users. Nothing in the gateway is mocked.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_PASSWORD = "TestPass@123!"
_ENV = {
    "AETHER_SECRET_KEY": "test-secret-key-12345678901234567890",
    "MAX_LOGIN_ATTEMPTS_PER_IP": "1000",
    "MAX_REGISTRATIONS_PER_IP": "1000",
    "EMAIL_ENABLED": "false",
}


@pytest.fixture(scope="module")
def gw(tmp_path_factory):
    import aether_os.core.db as db_mod
    import aether_os.core.pipeline_state as ps_mod
    import aether_os.core.rate_limiter as rl_mod
    from aether_os.gateway.api import create_app
    from aether_os.gateway.auth import decode_access_token

    db_file = str(tmp_path_factory.mktemp("gw") / "gw.db")
    saved = {k: os.environ.get(k) for k in (*_ENV, "DATABASE_URL")}
    os.environ.update(_ENV, DATABASE_URL=f"sqlite+aiosqlite:///{db_file}")
    db_mod._engine = None
    db_mod._session_factory = None
    rl_mod._mem = rl_mod._MemoryStore()
    rl_mod._instance = None
    rl_mod._redis_available = False
    rl_mod._async_redis_client = None
    # The Redis client is cached per process but bound to the event loop that made it;
    # each TestClient has its own loop, so start this module with a fresh client.
    ps_mod._redis = None

    def sql(stmt, args=()):
        conn = sqlite3.connect(db_file)
        try:
            rows = conn.execute(stmt, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    # The password shield asks an outside breach service; tests make no network calls.
    safe = dict(new_callable=AsyncMock, return_value=(True, ""))
    with patch("aether_os.gateway.routers.auth_router.check_password_safety", **safe), \
         patch("aether_os.gateway.routers.auth_password_router.check_password_safety", **safe), \
         TestClient(create_app()) as client:

        def session_of(body, email):
            claims = decode_access_token(body["access_token"])
            return SimpleNamespace(
                email=email, token=body["access_token"], refresh=body["refresh_token"],
                org_id=claims["org_id"], org_slug=claims["org_slug"], user_id=claims["user_id"],
                claims=claims, auth={"Authorization": f"Bearer {body['access_token']}"},
            )

        def register(name):
            email = f"{name}_{uuid.uuid4().hex[:10]}@test.com"
            resp = client.post("/auth/register", json={
                "email": email, "password": _PASSWORD, "org_name": name,
                "terms_accepted": True, "dpa_accepted": True,
            })
            assert resp.status_code == 200, resp.text
            sql("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
            return session_of(resp.json(), email)

        def login(email, password=_PASSWORD):
            resp = client.post("/auth/login", json={"email": email, "password": password})
            assert resp.status_code == 200, resp.text
            return session_of(resp.json(), email)

        def user_with_role(role, org_id):
            """A real user moved into `org_id` with `role`, signed in after the change."""
            email = register("tmp").email
            sql("UPDATE users SET role = ?, org_id = ? WHERE email = ?", (role, org_id, email))
            return login(email)

        yield SimpleNamespace(client=client, app=client.app, sql=sql, password=_PASSWORD,
                              register=register, login=login, user_with_role=user_with_role)

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    db_mod._engine = None
    db_mod._session_factory = None
    ps_mod._redis = None
