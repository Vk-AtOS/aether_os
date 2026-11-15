"""KAN-158: deleting an organisation is final. A deleted org refuses every token, so a restore route could never be
reached (and the users it would restore are anonymised); the route was removed instead of left lying."""


def test_owner_delete_is_final_and_there_is_no_restore_route(gw):
    org = gw.register("deleteme")
    assert gw.client.delete("/org", headers=org.auth).status_code in (200, 503)
    # The deleted org's own owner token is refused everywhere, including where a restore would have to be called.
    assert gw.client.get("/account/settings", headers=org.auth).status_code in (401, 403)
    assert gw.client.post("/org/restore", headers=org.auth).status_code in (404, 405)
    assert gw.sql("SELECT is_deleted FROM organisations WHERE id=?", (org.org_id,))[0][0] == 1


def test_only_an_owner_can_delete(gw):
    org = gw.register("keepme")
    admin = gw.user_with_role("admin", org.org_id)
    assert gw.client.delete("/org", headers=admin.auth).status_code == 403
    assert gw.client.get("/account/settings", headers=org.auth).status_code == 200
