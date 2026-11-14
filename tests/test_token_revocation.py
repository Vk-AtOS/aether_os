"""Access-token revocation: checked on every request whatever Redis looked like at
startup, fails closed when Redis cannot answer, and covers password change/reset.

Real /auth/* endpoints and the real local Redis. Skipped, not faked, when Redis is
not running.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from aether_os.core.pipeline_state import REDIS_URL
from aether_os.gateway.auth import create_access_token

_PROBE = "/auth/my-orgs"
_DEAD_REDIS = "redis://127.0.0.1:1/0"


@pytest.fixture(scope="module")
def redis_sync():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL}: {exc}")
    yield client
    client.close()


def _latched_off():
    """core.pipeline_state.get_redis() after a failed startup ping: None for the life of the process."""
    return patch("aether_os.gateway.auth_refresh.get_redis", new_callable=AsyncMock, return_value=None)


def _get(gw, s):
    return gw.client.get(_PROBE, headers=s.auth)


def test_logged_out_token_is_refused_even_if_redis_was_down_at_startup(gw, redis_sync):
    s = gw.register("latch")
    assert gw.client.post("/auth/logout", headers=s.auth).status_code == 200
    with _latched_off(), patch("aether_os.gateway.auth_refresh._own_client", None):
        # Before the fix the blacklist check was skipped here and this was 200.
        assert _get(gw, s).status_code == 401


def test_live_token_still_works_when_redis_was_down_at_startup_but_is_up_now(gw, redis_sync):
    s = gw.register("latchok")
    with _latched_off(), patch("aether_os.gateway.auth_refresh._own_client", None):
        assert _get(gw, s).status_code == 200


def test_requests_fail_closed_when_redis_cannot_answer(gw, redis_sync):
    s = gw.register("down")
    with _latched_off(), patch("aether_os.gateway.auth_refresh.REDIS_URL", _DEAD_REDIS), \
         patch("aether_os.gateway.auth_refresh._own_client", None):
        assert _get(gw, s).status_code == 503
        # Sibling dependencies sit on get_current_user: the run check and the SSE token exchange.
        assert gw.client.post("/factory/runs/nope/sse-token", headers=s.auth).status_code == 503
        assert gw.client.get("/factory/runs/nope/run-app/status", headers=s.auth).status_code == 503
    assert _get(gw, s).status_code == 200  # nothing was revoked by the outage


def test_token_without_jti_cannot_be_revoked_so_it_is_refused(gw, redis_sync):
    s = gw.register("nojti")
    claims = {k: v for k, v in s.claims.items() if k not in ("jti", "exp", "iat")}
    with patch("aether_os.gateway.auth.uuid.uuid4", return_value=""):  # setdefault("jti", "") -> falsy
        token = create_access_token(claims)
    assert gw.client.get(_PROBE, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_change_kills_other_sessions_access_tokens_and_keeps_this_one(gw, redis_sync):
    s1 = gw.register("pwc")
    s2 = gw.login(s1.email)
    assert _get(gw, s2).status_code == 200
    resp = gw.client.post("/auth/change-password", headers=s1.auth,
                          json={"current_password": gw.password, "new_password": "NewPass@4567!"})
    assert resp.status_code == 200, resp.text
    assert _get(gw, s2).status_code == 401   # was valid for up to an hour before the fix
    assert _get(gw, s1).status_code == 200   # the session that changed the password survives
    time.sleep(1.1)                          # iat has one-second resolution
    assert _get(gw, gw.login(s1.email, "NewPass@4567!")).status_code == 200


def test_admin_reset_kills_the_users_access_tokens(gw, redis_sync):
    owner = gw.register("adm")
    member = gw.user_with_role("member", owner.org_id)
    assert _get(gw, member).status_code == 200
    with patch("aether_os.gateway.services.admin_service._send_password_reset_email",
               new_callable=AsyncMock, return_value=False):
        resp = gw.client.post(f"/admin/users/{member.user_id}/reset-password", headers=owner.auth)
    assert resp.status_code == 200, resp.text
    assert _get(gw, member).status_code == 401
    assert _get(gw, owner).status_code == 200  # only the reset user is affected


def test_password_reset_kills_every_access_token(gw, redis_sync):
    s = gw.register("pwr")
    redis_sync.set("pw_reset:tok-" + s.user_id, s.user_id, ex=60)
    resp = gw.client.post("/auth/password-reset-confirm",
                          json={"token": "tok-" + s.user_id, "new_password": "Reset@98765!x"})
    assert resp.status_code == 200, resp.text
    assert _get(gw, s).status_code == 401


def test_deleted_orgs_api_key_stops_working(gw, redis_sync):
    s = gw.register("apikey")
    created = gw.client.post("/auth/api-keys", headers=s.auth, json={"name": "k"})
    assert created.status_code == 200, created.text
    key = next(v for v in created.json().values() if isinstance(v, str) and v.startswith("aesk_"))
    auth = {"Authorization": f"Bearer {key}"}
    assert gw.client.get("/billing/status", headers=auth).status_code == 200
    gw.sql("UPDATE organisations SET is_deleted = 1 WHERE id = ?", (s.org_id,))
    assert gw.client.get("/billing/status", headers=auth).status_code == 401


def test_liveness_verdict_is_cached_briefly_and_revoke_clears_it(monkeypatch):
    """A burst on one token costs one Redis round trip; logout on this worker is seen at once."""
    import asyncio
    import time as _t
    import aether_os.gateway.auth_refresh as ar

    class R:
        calls = 0
        revoked = False

        async def mget(self, keys):
            R.calls += 1
            return [("1" if R.revoked else None)] + [None] * (len(keys) - 1)

        async def set(self, *a, **k):
            R.revoked = True

    r = R()

    async def red():
        return r

    monkeypatch.setattr(ar, "_redis", red)
    ar._verdicts.clear()
    claims = {"jti": "cj1", "fam": "f", "user_id": "u", "exp": _t.time() + 600}

    async def go():
        for _ in range(5):
            await ar.assert_access_token_live(claims)
        assert R.calls == 1
        await ar.revoke_session(claims)
        try:
            await ar.assert_access_token_live(claims)
        except Exception as e:
            return e.status_code

    assert asyncio.run(go()) == 401
    assert R.calls == 2
