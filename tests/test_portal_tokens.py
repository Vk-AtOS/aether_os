"""Client portal: an org admin issues a per-project token (shown once, stored as a
hash, expiring, revocable, ledgered), and POST /portal/{id}/approve records a
ledgered client approval that the owning org can read.

Real gateway, real database, real ledger; nothing is mocked.
"""
from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import pytest

from aether_os.core.pipeline_state import get_control, set_control


@pytest.fixture(scope="module")
def portal(gw, tmp_path_factory):
    import aether_os.core.projects as pm_mod

    mp = pytest.MonkeyPatch()
    home = tmp_path_factory.mktemp("home")
    mp.setenv("HOME", str(home))
    mp.setattr(pm_mod, "_manager", pm_mod.ProjectManager(root=home / ".aether_os" / "projects"))

    a, b = gw.register("ptoka"), gw.register("ptokb")
    member = gw.user_with_role("member", a.org_id)

    def new_run(org_id):
        run_id = str(uuid.uuid4())
        gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
               "VALUES (?, ?, 'factory: p', 'completed', ?, 0, 1)", (run_id, org_id, time.time()))
        return run_id

    yield SimpleNamespace(a=a, b=b, member=member, run_a=new_run(a.org_id), run_b=new_run(b.org_id), new_run=new_run)
    mp.undo()


def _issue(gw, who, run_id, **body):
    return gw.client.post(f"/factory/runs/{run_id}/portal-tokens", headers=who.auth, json=body)


def _status(gw, run_id, token):
    return gw.client.get(f"/portal/{run_id}/status", headers={"X-Portal-Token": token})


def _approve(gw, run_id, headers, approved=True, comment=None):
    return gw.client.post(f"/portal/{run_id}/approve", headers=headers,
                          json={"approved": approved, "comment": comment})


def _ledger(gw, org_id, action):
    return [json.loads(m) for (m,) in gw.sql(
        "SELECT log_metadata FROM audit_log WHERE org_id = ? AND action = ?", (org_id, action))]


def test_only_an_admin_of_the_owning_org_can_issue(gw, portal):
    assert gw.client.post(f"/factory/runs/{portal.run_a}/portal-tokens", json={}).status_code == 401
    assert _issue(gw, portal.member, portal.run_a).status_code == 403
    assert _issue(gw, portal.b, portal.run_a).status_code == 404       # not their run: not even confirmed
    assert gw.client.get(f"/factory/runs/{portal.run_a}/portal-tokens", headers=portal.member.auth).status_code == 403
    assert _ledger(gw, portal.a.org_id, "policy.denied")               # the refusals are on the ledger


def test_token_is_shown_once_stored_as_a_hash_and_expires_in_30_days(gw, portal):
    resp = _issue(gw, portal.a, portal.run_a, label="Acme client")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["token"]
    assert token.startswith("aept_") and len(token) > 40
    assert body["label"] == "Acme client" and body["status"] == "active"
    assert 29.9 * 86400 < body["expires_at"] - body["created_at"] <= 30 * 86400

    # Nowhere in the database or on disk in plaintext.
    stored = gw.sql("SELECT token_hash FROM portal_tokens WHERE id = ?", (body["id"],))[0][0]
    assert stored != token and len(stored) == 64
    rows = gw.sql("SELECT * FROM portal_tokens") + gw.sql("SELECT log_metadata FROM audit_log")
    assert token not in json.dumps(rows, default=str)

    listed = gw.client.get(f"/factory/runs/{portal.run_a}/portal-tokens", headers=portal.a.auth)
    assert listed.status_code == 200
    assert token not in listed.text and stored not in listed.text and "token_hash" not in listed.text
    assert [t["id"] for t in listed.json()["tokens"]] == [body["id"]]

    assert _status(gw, portal.run_a, token).status_code == 200
    assert _status(gw, portal.run_b, token).status_code == 401          # one project only
    issued = _ledger(gw, portal.a.org_id, "portal.token_issued")
    assert issued and issued[-1]["token_id"] == body["id"]
    assert [u["token_id"] for u in _ledger(gw, portal.a.org_id, "portal.token_used")] == [body["id"]]


def test_expired_token_is_refused(gw, portal):
    body = _issue(gw, portal.a, portal.run_a, expires_in_days=1).json()
    assert _status(gw, portal.run_a, body["token"]).status_code == 200
    gw.sql("UPDATE portal_tokens SET expires_at = ? WHERE id = ?", (time.time() - 1, body["id"]))
    assert _status(gw, portal.run_a, body["token"]).status_code == 401
    assert _issue(gw, portal.a, portal.run_a, expires_in_days=0).status_code == 422
    assert _issue(gw, portal.a, portal.run_a, expires_in_days=3650).status_code == 422


def test_revoked_token_is_refused_and_revocation_is_ledgered_once(gw, portal):
    body = _issue(gw, portal.a, portal.run_a).json()
    url = f"/factory/runs/{portal.run_a}/portal-tokens/{body['id']}"
    assert gw.client.delete(url, headers=portal.member.auth).status_code == 403
    assert gw.client.delete(f"/factory/runs/{portal.run_b}/portal-tokens/{body['id']}",
                            headers=portal.b.auth).status_code == 404   # another org cannot revoke it
    assert _status(gw, portal.run_a, body["token"]).status_code == 200

    first = gw.client.delete(url, headers=portal.a.auth)
    assert first.status_code == 200 and first.json()["status"] == "revoked"
    assert gw.client.delete(url, headers=portal.a.auth).json()["revoked_at"] == first.json()["revoked_at"]
    assert _status(gw, portal.run_a, body["token"]).status_code == 401
    revoked = [r for r in _ledger(gw, portal.a.org_id, "portal.token_revoked") if r["token_id"] == body["id"]]
    assert len(revoked) == 1


def test_bad_token_gets_401_whether_or_not_the_project_exists(gw, portal):
    for run_id in (portal.run_a, str(uuid.uuid4())):
        assert _approve(gw, run_id, {"X-Portal-Token": "aept_guess"}).status_code == 401
        assert _approve(gw, run_id, {}).status_code == 401


def test_client_approval_is_recorded_ledgered_idempotent_and_readable_by_the_org(gw, portal):
    run_id = portal.new_run(portal.a.org_id)
    issued = _issue(gw, portal.a, run_id, label="Acme client").json()
    headers = {"X-Portal-Token": issued["token"]}

    first = _approve(gw, run_id, headers, comment="Looks right")
    assert first.status_code == 200, first.text                        # was 500 for everyone
    body = first.json()
    assert body["approved"] is True and body["duplicate"] is False and body["recorded_by"] == "Acme client"
    assert body["applied_to"] is None and body["message"] == "Approval recorded."

    again = _approve(gw, run_id, headers, comment="Looks right").json()
    assert again["approval_id"] == body["approval_id"] and again["duplicate"] is True
    assert gw.sql("SELECT count(*) FROM portal_approvals WHERE project_id = ?", (run_id,))[0][0] == 1

    # A different decision is a new record, not an overwrite.
    changed = _approve(gw, run_id, headers, approved=False, comment="Change the logo").json()
    assert changed["approval_id"] != body["approval_id"] and changed["message"] == "Change request recorded."

    # The signed-in owner approving is recorded as that user.
    by_user = _approve(gw, run_id, portal.a.auth).json()
    assert by_user["recorded_by"] == portal.a.email

    listed = gw.client.get(f"/factory/runs/{run_id}/portal-approvals", headers=portal.a.auth)
    assert listed.status_code == 200
    approvals = listed.json()["approvals"]
    assert [(a["actor_kind"], a["approved"], a["comment"]) for a in approvals] == [
        ("user", True, None), ("portal_token", False, "Change the logo"), ("portal_token", True, "Looks right")]
    assert approvals[-1]["actor_id"] == issued["id"] and approvals[-1]["created_at"] == body["recorded_at"]
    assert gw.client.get(f"/factory/runs/{run_id}/portal-approvals", headers=portal.b.auth).status_code == 404

    ledgered = [e for e in _ledger(gw, portal.a.org_id, "portal.client_approval")]
    assert [e["approval_id"] for e in ledgered if e["approval_id"] in {a["id"] for a in approvals}] \
        == [a["id"] for a in reversed(approvals)]
    chain_linked = gw.sql("SELECT count(*) FROM audit_log WHERE action = 'portal.client_approval' "
                          "AND org_id = ? AND prev_hash IS NOT NULL", (portal.a.org_id,))[0][0]
    assert chain_linked == len(ledgered)                               # each one is on the hash chain


def test_approval_releases_a_build_waiting_at_spec_review(gw, portal):
    run_id = portal.new_run(portal.a.org_id)
    headers = {"X-Portal-Token": _issue(gw, portal.a, run_id).json()["token"]}
    call = gw.client.portal.call
    call(set_control, run_id, "spec_review")       # what orchestrator/spec_review_gate.py sets while it waits

    rejected = _approve(gw, run_id, headers, approved=False, comment="not yet").json()
    assert rejected["applied_to"] is None and call(get_control, run_id) == "spec_review"

    approved = _approve(gw, run_id, headers).json()
    assert approved["applied_to"] == "spec_review"
    assert call(get_control, run_id) == "spec_approved"                # the flag the gate polls for
    assert gw.sql("SELECT applied_to FROM portal_approvals WHERE id = ?", (approved["approval_id"],))[0][0] \
        == "spec_review"


def test_approve_unknown_project_is_404_for_a_signed_in_org(gw, portal):
    assert _approve(gw, str(uuid.uuid4()), portal.a.auth).status_code == 404
