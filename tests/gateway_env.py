"""Shared test helper: the real gateway on a throwaway SQLite database, with one
registered owner. Not a test module (no test_ prefix)."""
from __future__ import annotations

import contextlib
import os
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

ENV = {
    "AETHER_SECRET_KEY": "test-secret-key-12345678901234567890",
    "RAZORPAY_KEY_ID": "rzp_test_id",
    "RAZORPAY_KEY_SECRET": "rzp_test_secret",
    "RAZORPAY_WEBHOOK_SECRET": "whsec_test",
}


@contextlib.contextmanager
def gateway_env(tmp_dir):
    import aether_os.core.db as db_mod
    import aether_os.core.rate_limiter as rl_mod
    from aether_os.gateway.api import create_app
    from aether_os.gateway.auth import decode_access_token

    db_file = str(tmp_dir / "gw.db")
    saved = {k: os.environ.get(k) for k in (*ENV, "DATABASE_URL")}
    os.environ.update(ENV, DATABASE_URL=f"sqlite+aiosqlite:///{db_file}")
    db_mod._engine = None
    db_mod._session_factory = None
    rl_mod._mem = rl_mod._MemoryStore()
    rl_mod._instance = None
    rl_mod._redis_available = False
    rl_mod._async_redis_client = None

    def sql(stmt, args=()):
        conn = sqlite3.connect(db_file)
        try:
            rows = conn.execute(stmt, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    try:
        with patch("aether_os.gateway.routers.auth_router.check_password_safety",
                   new_callable=AsyncMock, return_value=(True, "")), \
             TestClient(create_app()) as client:
            email = f"owner_{uuid.uuid4().hex[:10]}@test.com"
            resp = client.post("/auth/register", json={
                "email": email, "password": "TestPass@123!", "org_name": "orga",
                "terms_accepted": True, "dpa_accepted": True,
            })
            assert resp.status_code == 200, resp.text
            sql("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
            token = resp.json()["access_token"]
            claims = decode_access_token(token)
            yield SimpleNamespace(client=client, sql=sql, org_id=claims["org_id"], claims=claims,
                                  auth={"Authorization": f"Bearer {token}"})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        db_mod._engine = None
        db_mod._session_factory = None
