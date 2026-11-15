"""Token state fails closed: the MFA replay check, SSE exchange tokens and account
deletion all answer 503 (and change nothing) when Redis cannot be consulted.

Real Redis for the happy paths (as the other gateway tests use); "Redis down" is a
token store whose commands raise, the way a dead connection does.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

import aether_os.core.pipeline_state as pipeline_state
import aether_os.gateway.auth_mfa as mfa
import aether_os.gateway.auth_refresh as refresh
import aether_os.gateway.routers.account_router as account_router


class DeadRedis:
    def __getattr__(self, _name):
        async def fail(*_a, **_k):
            raise ConnectionError("Redis is down")
        return fail

    def pipeline(self, *_a, **_k):
        raise ConnectionError("Redis is down")


def _fresh_clients(monkeypatch):
    """Redis clients are bound to the event loop that made them; this test has its own loop."""
    monkeypatch.setattr(refresh, "_own_client", None)
    monkeypatch.setattr(pipeline_state, "_redis", None)


async def _dead():
    return DeadRedis()


@pytest.mark.asyncio
async def test_mfa_replay_check_fails_closed_and_codes_work_once(monkeypatch):
    monkeypatch.setattr(mfa, "token_store", _dead)
    with pytest.raises(HTTPException) as exc:
        await mfa._claim_totp_code("u1", "123456")
    assert exc.value.status_code == 503
    monkeypatch.undo()

    _fresh_clients(monkeypatch)
    user = f"u-{uuid.uuid4().hex}"
    assert await mfa._claim_totp_code(user, "123456") is True
    assert await mfa._claim_totp_code(user, "123456") is False        # replay
    assert await mfa._claim_totp_code(user, "654321") is True


@pytest.mark.asyncio
async def test_sse_tokens_are_redis_only_and_single_use(monkeypatch):
    monkeypatch.setattr(refresh, "_redis", _dead)
    for call in (refresh.sse_token_set("t", "org", "run"), refresh.sse_token_pop("t")):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 503
    monkeypatch.undo()

    _fresh_clients(monkeypatch)
    token = uuid.uuid4().hex
    await refresh.sse_token_set(token, "org1", "run1")
    assert await refresh.sse_token_pop(token) == {"org_id": "org1", "run_id": "run1"}
    assert await refresh.sse_token_pop(token) is None
    assert await refresh.sse_token_pop("never-issued") is None


def test_sse_exchange_route_is_503_when_redis_is_down(gw, monkeypatch):
    owner = gw.register("sse503")
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'running', 0, 0, 1)", (run_id, owner.org_id))
    issued = gw.client.post(f"/factory/runs/{run_id}/sse-token", headers=owner.auth)
    assert issued.status_code == 200
    # Only the SSE store is broken here, so the bearer-token check itself still works.
    monkeypatch.setattr(refresh, "sse_token_set", _raise_503)
    assert gw.client.post(f"/factory/runs/{run_id}/sse-token", headers=owner.auth).status_code == 503


async def _raise_503(*_a, **_k):
    raise refresh._UNAVAILABLE


def test_account_deletion_ends_every_session_or_does_nothing(gw, monkeypatch):
    user = gw.register("deleteme")
    other_session = gw.login(user.email)

    async def cannot_revoke(_user_id, keep_family=None):
        raise refresh._UNAVAILABLE

    monkeypatch.setattr(account_router, "revoke_user_sessions", cannot_revoke)
    resp = gw.client.delete("/account", headers=user.auth)
    assert resp.status_code == 503
    assert gw.sql("SELECT is_active FROM users WHERE id = ?", (user.user_id,))[0][0] in (1, True)
    monkeypatch.undo()

    assert gw.client.delete("/account", headers=user.auth).status_code == 200
    # Both the session that deleted the account and one on another device are dead.
    assert gw.client.get("/account/preferences", headers=user.auth).status_code == 401
    assert gw.client.get("/account/preferences", headers=other_session.auth).status_code == 401
    assert gw.client.post("/auth/refresh", json={"refresh_token": other_session.refresh}).status_code == 401


@pytest.mark.asyncio
async def test_oauth_state_is_redis_backed_single_use_and_provider_bound(monkeypatch):
    monkeypatch.setattr(refresh, "_redis", _dead)
    for call in (refresh.oauth_state_set("s", "google"), refresh.oauth_state_pop("s", "google")):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 503
    monkeypatch.undo()

    _fresh_clients(monkeypatch)
    state = uuid.uuid4().hex
    await refresh.oauth_state_set(state, "google")
    assert await refresh.oauth_state_pop(state, "github") is False   # wrong provider; and it is spent
    assert await refresh.oauth_state_pop(state, "google") is False
    await refresh.oauth_state_set(state, "google")
    assert await refresh.oauth_state_pop(state, "google") is True
    assert await refresh.oauth_state_pop(state, "google") is False
