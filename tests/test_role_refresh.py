"""KAN-101: a JWT's role/org claims must not outlive a change to the user row."""


def test_demoted_admin_loses_admin_rights_with_the_old_token(gw):
    admin = gw.register("owner")
    other = gw.user_with_role("admin", admin.org_id)
    ok = gw.client.post("/account/settings", headers=other.auth, json={"autonomous_mode": False})
    assert ok.status_code == 200, ok.text
    gw.sql("UPDATE users SET role = 'viewer' WHERE email = ?", (other.email,))
    r = gw.client.post("/account/settings", headers=other.auth, json={"autonomous_mode": False})
    assert r.status_code == 403
