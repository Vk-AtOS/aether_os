"""KAN-162: org-wide decisions inbox is tenant scoped, bounded and role checked; viewers cannot decide (D7)."""
import asyncio

from aether_os.core.decisions.decision_engine import Decision, get_decision_engine


def _make(org_id, run_id, title="Approve spec"):
    d = Decision(run_id=run_id, org_id=org_id, decision_type="spec_review", title=title, what="w", why="y")
    asyncio.run(get_decision_engine().request_approval(d))
    return d


def _insert_run(gw, rid, org):
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'running', 0, 0, 1)", (rid, org.org_id))


def _run(gw, org):
    rid = f"run-{org.org_id[:8]}"
    _insert_run(gw, rid, org)
    return rid


def test_inbox_lists_only_own_org_pending_across_runs_and_paginates(gw):
    a, b = gw.register("inboxa"), gw.register("inboxb")
    ra, rb = _run(gw, a), _run(gw, b)
    mine = [_make(a.org_id, ra, f"mine{i}") for i in range(3)]
    _make(b.org_id, rb, "theirs")
    got = gw.client.get("/factory/decisions", headers=a.auth).json()["decisions"]
    assert {d["id"] for d in got} == {d.id for d in mine}
    assert len(gw.client.get("/factory/decisions?limit=2", headers=a.auth).json()["decisions"]) == 2
    assert gw.client.get("/factory/decisions?limit=101", headers=a.auth).status_code == 422
    assert gw.client.get("/factory/decisions?status=bogus", headers=a.auth).status_code == 422


def test_viewer_cannot_decide_member_can_and_a_decision_resolves_once(gw):
    org = gw.register("inboxrole")
    rid = _run(gw, org)
    d = _make(org.org_id, rid)
    viewer = gw.user_with_role("viewer", org.org_id)
    member = gw.user_with_role("member", org.org_id)
    url = f"/factory/runs/{rid}/decisions/{d.id}/decide"
    assert gw.client.post(url, headers=viewer.auth, json={"decision": "approve"}).status_code == 403
    assert gw.client.post(f"/factory/runs/{rid}/decisions/{d.id}/approve", headers=viewer.auth).status_code == 403
    assert gw.client.post(url, headers=member.auth, json={"decision": "approve"}).status_code == 200
    assert gw.client.get("/factory/decisions", headers=member.auth).json()["decisions"] == []
    # A second reviewer cannot flip the outcome the pipeline already acted on.
    assert gw.client.post(url, headers=member.auth, json={"decision": "deny"}).status_code == 409


def test_decision_must_belong_to_the_run_in_the_url(gw):
    org = gw.register("inboxrun")
    r1, r2 = _run(gw, org), "run-other"
    _insert_run(gw, r2, org)
    d = _make(org.org_id, r1)
    assert gw.client.post(f"/factory/runs/{r2}/decisions/{d.id}/decide", headers=org.auth,
                          json={"decision": "approve"}).status_code == 404


def test_reject_really_denies_and_a_body_without_a_verdict_is_refused(gw):
    org = gw.register("inboxdeny")
    rid = _run(gw, org)
    d1, d2, d3 = (_make(org.org_id, rid, f"d{i}") for i in range(3))
    base = f"/factory/runs/{rid}/decisions"
    # The dashboard sends {approved: false}; that must deny, not approve.
    assert gw.client.post(f"{base}/{d1.id}/decide", headers=org.auth, json={"approved": False}).json()["status"] == "denied"
    assert gw.client.post(f"{base}/{d2.id}/decide", headers=org.auth, json={"decision": "deny"}).json()["status"] == "denied"
    assert gw.client.post(f"{base}/{d3.id}/decide", headers=org.auth, json={}).status_code == 422
    assert gw.client.post(f"{base}/{d3.id}/decide", headers=org.auth, json={"decision": "approve"}).json()["status"] == "approved"
