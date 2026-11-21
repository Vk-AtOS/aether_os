"""KAN-154: resolving a conflict marks it resolved for the whole organisation and records who resolved it."""


def test_resolution_is_shared_in_the_org_and_names_the_resolver(gw):
    org = gw.register("conflictorg")
    other = gw.user_with_role("member", org.org_id)
    body = {"conflict_id": "C1", "resolution": "use eventual consistency", "description": "Latency vs strict consistency"}
    r = gw.client.post("/intelligence/conflict-resolver/resolve", json=body, headers=org.auth)
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    # A different member of the same org sees it as resolved, with the resolver's id.
    got = gw.client.get("/intelligence/conflict-resolver/resolved", headers=other.auth).json()["resolved"]
    assert got[key]["resolution"] == "use eventual consistency"
    assert got[key]["resolved_by"]
    # Another organisation does not.
    stranger = gw.register("conflictstranger")
    assert gw.client.get("/intelligence/conflict-resolver/resolved", headers=stranger.auth).json()["resolved"] == {}
