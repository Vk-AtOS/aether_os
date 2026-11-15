"""KAN-186/H5: an org can require MFA for owners and admins; the server enforces it on every request."""
import time


def _setup(gw, name):
    owner = gw.register(name)
    admin = gw.user_with_role("admin", owner.org_id)
    member = gw.user_with_role("member", owner.org_id)
    return owner, admin, member


def test_admin_without_mfa_is_locked_to_enrolment_after_the_grace_period(gw):
    owner, admin, member = _setup(gw, "mfapol")
    # Switching the policy on starts a grace period: nothing changes yet.
    r = gw.client.post("/account/settings", headers=owner.auth, json={"require_admin_mfa": True})
    assert r.status_code == 200, r.text
    assert gw.client.get("/webhooks", headers=admin.auth).status_code == 200
    # Grace over: the admin is refused everywhere except enrolment, members are untouched.
    gw.sql("UPDATE organisations SET admin_mfa_grace_until = ? WHERE id = ?", (time.time() - 1, owner.org_id))
    r = gw.client.get("/webhooks", headers=admin.auth)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "mfa_required"
    assert gw.client.post("/webhooks", headers=admin.auth, json={}).status_code == 403
    assert gw.client.get("/workspaces", headers=member.auth).status_code == 200
    assert gw.client.get("/account/settings", headers=admin.auth).status_code == 200      # can read the policy
    assert gw.client.post("/auth/mfa/setup", headers=admin.auth).status_code != 403        # can enrol
    # With MFA on the account the admin is let through again; policy off lets everyone through.
    gw.sql("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (admin.user_id,))
    assert gw.client.get("/webhooks", headers=admin.auth).status_code == 200
    gw.sql("UPDATE users SET mfa_enabled = 0 WHERE id = ?", (admin.user_id,))
    assert gw.client.post("/account/settings", headers=owner.auth, json={"require_admin_mfa": False}).status_code == 200
    assert gw.client.get("/webhooks", headers=admin.auth).status_code == 200


def test_policy_can_only_be_changed_by_admins_and_is_validated(gw):
    owner, admin, member = _setup(gw, "mfapol2")
    assert gw.client.post("/account/settings", headers=member.auth, json={"require_admin_mfa": True}).status_code == 403
    assert gw.client.post("/account/settings", headers=owner.auth, json={"require_admin_mfa": "yes"}).status_code == 422
    assert gw.client.post("/account/settings", headers=owner.auth,
                          json={"require_admin_mfa": True, "mfa_grace_days": 99}).status_code == 422
