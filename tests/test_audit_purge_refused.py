"""DELETE /audit/logs/purge never deletes: it refuses and records the attempt."""
from __future__ import annotations

import time

import pytest

from aether_os.tests.gateway_env import gateway_env


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with gateway_env(tmp_path_factory.mktemp("purge")) as e:
        yield e


def _audit_rows(env, action=None):
    if action:
        return env.sql("SELECT user_id, log_metadata, prev_hash FROM audit_log "
                       "WHERE org_id = ? AND action = ?", (env.org_id, action))
    return env.sql("SELECT id FROM audit_log WHERE org_id = ?", (env.org_id,))


def test_purge_is_refused_deletes_nothing_and_is_audited(env):
    # An old row that the previous implementation would have deleted.
    env.sql("INSERT INTO audit_log (id, org_id, user_id, action, resource_type, resource_id, created_at) "
            "VALUES ('old-row', ?, 'u', 'login', 'session', 's', ?)", (env.org_id, time.time() - 400 * 86400))
    before = {r[0] for r in _audit_rows(env)}
    assert "old-row" in before

    resp = env.client.delete("/audit/logs/purge", params={"days_to_keep": 30}, headers=env.auth)

    assert resp.status_code == 410, resp.text
    assert "append-only" in resp.json()["detail"]
    after = {r[0] for r in _audit_rows(env)}
    assert before <= after, "purge removed audit rows"
    attempts = _audit_rows(env, "audit.purge_refused")
    assert len(attempts) == 1
    user_id, metadata, chain_link = attempts[0]
    assert user_id == env.claims["user_id"]
    assert '"days_to_keep": 30' in metadata
    assert chain_link, "the refusal must be linked into the audit chain"


def test_purge_by_non_admin_is_403_and_still_audited(env):
    # The role is read from the user's row, so demote the real user (a forged claim decides nothing).
    uid = env.claims["user_id"]
    env.sql("UPDATE users SET role = 'member' WHERE id = ?", (uid,))
    try:
        before = len(_audit_rows(env, "audit.purge_refused"))
        resp = env.client.delete("/audit/logs/purge", headers=env.auth)
    finally:
        env.sql("UPDATE users SET role = 'owner' WHERE id = ?", (uid,))
    assert resp.status_code == 403
    assert len(_audit_rows(env, "audit.purge_refused")) == before + 1


def test_purge_requires_authentication(env):
    assert env.client.delete("/audit/logs/purge").status_code == 401
