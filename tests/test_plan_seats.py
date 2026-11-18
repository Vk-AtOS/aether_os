"""KAN-186: a plan's seats cap how many active users an org can have; every way of adding one is gated."""
import asyncio

from aether_os.core.policy.rules import Facts, evaluate


def test_rule_denies_the_user_after_the_last_seat_and_enterprise_is_uncapped():
    ok = evaluate("user.add", Facts(org_exists=True, plan="starter", role="admin", seats_used=4))
    full = evaluate("user.add", Facts(org_exists=True, plan="starter", role="admin", seats_used=5))
    assert ok.allowed and not full.allowed and full.reason == "quota_seats" and full.detail["limit"] == 5
    assert evaluate("user.add", Facts(org_exists=True, plan="enterprise", role="admin", seats_used=5000)).allowed
    assert not evaluate("user.add", Facts(org_exists=True, plan="starter", role="member", seats_used=0)).allowed


def _fill(gw, org, plan, n):
    gw.sql("UPDATE organisations SET plan = ? WHERE id = ?", (plan, org.org_id))
    have = gw.sql("SELECT COUNT(*) FROM users WHERE org_id = ?", (org.org_id,))[0][0]
    for _ in range(n - have):
        gw.user_with_role("member", org.org_id)


def test_invite_is_refused_with_402_when_the_plan_has_no_seat_left(gw):
    owner = gw.register("seats")
    _fill(gw, owner, "starter", 5)
    r = gw.client.post("/admin/users/invite", headers=owner.auth, json={"email": "x1@example.com", "role": "member"})
    assert r.status_code == 402 and r.json()["detail"]["error"] == "quota_seats"
    gw.sql("UPDATE organisations SET plan = 'enterprise' WHERE id = ?", (owner.org_id,))
    r = gw.client.post("/admin/users/invite", headers=owner.auth, json={"email": "x2@example.com", "role": "member"})
    assert r.status_code == 200, r.text


def test_scim_provisioning_cannot_exceed_the_seats_either(gw):
    owner = gw.register("seatscim")
    _fill(gw, owner, "starter", 5)
    token = gw.client.post("/settings/scim/rotate", headers=owner.auth).json()
    token = token.get("token") or token.get("scim_token")
    r = gw.client.post("/scim/v2/Users", headers={"Authorization": f"Bearer {token}"},
                       json={"userName": "idp-user@example.com"})
    assert r.status_code == 402, r.text


def test_saml_jit_provisioning_cannot_exceed_the_seats(gw):
    import pytest
    from fastapi import HTTPException
    from aether_os.gateway.auth_saml import _resolve_saml_user
    owner = gw.register("seatsaml")
    _fill(gw, owner, "starter", 5)
    with pytest.raises(HTTPException) as e:
        asyncio.run(_resolve_saml_user("new-jit@example.com", owner.org_id))
    assert e.value.status_code == 402
