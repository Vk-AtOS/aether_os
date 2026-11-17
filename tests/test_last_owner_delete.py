"""KAN-69 F23: the last owner could delete their own account."""


def test_last_owner_cannot_delete_the_account_but_a_member_can(gw):
    owner = gw.register("lastown")
    r = gw.client.delete("/account", headers=owner.auth)
    assert r.status_code == 409, r.text
    assert gw.sql("SELECT is_active FROM users WHERE id = ?", (owner.user_id,))[0][0]
    member = gw.user_with_role("member", owner.org_id)
    assert gw.client.delete("/account", headers=member.auth).status_code == 200
