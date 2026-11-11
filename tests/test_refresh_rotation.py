"""Refresh tokens: single use, replay revokes the family, logout and password change revoke.

Real /auth/* endpoints and the real local Redis (the token state store). Skipped,
not faked, when Redis is not running.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from aether_os.core.pipeline_state import REDIS_URL


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


def _refresh(gw, token):
    return gw.client.post("/auth/refresh", json={"refresh_token": token})


def test_refresh_rotates_and_old_token_is_dead(gw, redis_sync):
    s = gw.register("rot")
    first = _refresh(gw, s.refresh)
    assert first.status_code == 200, first.text
    pair = first.json()
    assert pair["refresh_token"] and pair["refresh_token"] != s.refresh
    new_auth = {"Authorization": f"Bearer {pair['access_token']}"}
    assert gw.client.get("/auth/my-orgs", headers=new_auth).status_code == 200

    # The spent token is rejected…
    assert _refresh(gw, s.refresh).status_code == 401
    # …and replaying it revoked the family: the successor pair is dead too.
    assert _refresh(gw, pair["refresh_token"]).status_code == 401
    assert gw.client.get("/auth/my-orgs", headers=new_auth).status_code == 401


def test_rotation_chain_works_when_each_token_is_used_once(gw, redis_sync):
    s = gw.register("chain")
    token = s.refresh
    for _ in range(3):
        resp = _refresh(gw, token)
        assert resp.status_code == 200, resp.text
        token = resp.json()["refresh_token"]


def test_replay_in_one_session_does_not_touch_another_session(gw, redis_sync):
    s1 = gw.register("iso")
    s2 = gw.login(s1.email)
    assert _refresh(gw, s1.refresh).status_code == 200
    assert _refresh(gw, s1.refresh).status_code == 401  # family of s1 revoked
    assert _refresh(gw, s2.refresh).status_code == 200  # s2 is a different family


def test_logout_revokes_the_refresh_token(gw, redis_sync):
    s = gw.register("out")
    assert gw.client.post("/auth/logout", headers=s.auth).status_code == 200
    assert _refresh(gw, s.refresh).status_code == 401
    assert gw.client.get("/auth/my-orgs", headers=s.auth).status_code == 401


def test_logout_after_refresh_revokes_the_rotated_token(gw, redis_sync):
    s = gw.register("out2")
    pair = _refresh(gw, s.refresh).json()
    auth = {"Authorization": f"Bearer {pair['access_token']}"}
    assert gw.client.post("/auth/logout", headers=auth).status_code == 200
    assert _refresh(gw, pair["refresh_token"]).status_code == 401


def test_password_change_revokes_other_sessions_only(gw, redis_sync):
    here = gw.register("pw")
    elsewhere = gw.login(here.email)
    new_password = "Another@Pass456!"
    resp = gw.client.post("/auth/change-password", headers=here.auth,
                          json={"current_password": gw.password, "new_password": new_password})
    assert resp.status_code == 200, resp.text

    assert _refresh(gw, elsewhere.refresh).status_code == 401
    assert _refresh(gw, here.refresh).status_code == 200  # the session that changed it stays

    time.sleep(1.1)  # iat has one-second resolution; see consume_refresh_token
    fresh = gw.login(here.email, new_password)
    assert _refresh(gw, fresh.refresh).status_code == 200


def test_password_reset_revokes_every_session(gw, redis_sync):
    s = gw.register("reset")
    reset_token = uuid.uuid4().hex
    redis_sync.set(f"pw_reset:{reset_token}", s.user_id, ex=300)  # what the reset e-mail carries
    resp = gw.client.post("/auth/password-reset-confirm",
                          json={"token": reset_token, "new_password": "Reset@Pass789!"})
    assert resp.status_code == 200, resp.text
    assert _refresh(gw, s.refresh).status_code == 401


def test_refresh_fails_closed_when_redis_is_down(gw, redis_sync):
    s = gw.register("down")
    with patch("aether_os.gateway.auth_refresh.get_redis", new_callable=AsyncMock, return_value=None):
        assert _refresh(gw, s.refresh).status_code == 503
        # Logout must not claim success when it revoked nothing.
        assert gw.client.post("/auth/logout", headers=s.auth).status_code == 503
    # Nothing was spent during the outage.
    assert _refresh(gw, s.refresh).status_code == 200


def test_access_token_is_still_not_a_refresh_token(gw, redis_sync):
    s = gw.register("type")
    assert _refresh(gw, s.token).status_code == 401
