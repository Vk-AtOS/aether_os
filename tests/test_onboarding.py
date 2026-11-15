"""KAN-165: onboarding progress is derived from real data and follows the org across browsers; dismissal is org-wide, admin only."""


def _steps(gw, who):
    return {s["id"]: s["done"] for s in gw.client.get("/onboarding", headers=who.auth).json()["steps"]}


def test_steps_follow_real_data_and_dismissal_is_org_wide_and_admin_only(gw):
    org = gw.register("onb")
    body = gw.client.get("/onboarding", headers=org.auth).json()
    assert body["dismissed"] is False and body["complete"] is False
    assert _steps(gw, org) == {"llm_key": False, "first_run": False, "invite_team": False, "plan": False, "sso": False}

    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) VALUES ('onb-r', ?, 'x', 'completed', 0, 0, 1)", (org.org_id,))
    member = gw.user_with_role("member", org.org_id)  # a second member = the team step
    gw.sql("UPDATE organisations SET plan='pro' WHERE id=?", (org.org_id,))
    got = _steps(gw, member)  # another person, another browser: same answer
    assert got["first_run"] and got["invite_team"] and got["plan"] and not got["llm_key"]

    assert gw.client.post("/onboarding/dismiss", headers=member.auth).status_code == 403
    assert gw.client.get("/onboarding", headers=member.auth).json()["dismissed"] is False
    assert gw.client.post("/onboarding/dismiss", headers=org.auth).status_code == 200
    assert gw.client.post("/onboarding/dismiss", headers=org.auth).status_code == 200  # idempotent
    assert gw.client.get("/onboarding", headers=member.auth).json()["dismissed"] is True


def test_other_orgs_are_not_counted(gw):
    a, b = gw.register("onba"), gw.register("onbb")
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) VALUES ('onb-x', ?, 'x', 'completed', 0, 0, 1)", (a.org_id,))
    assert _steps(gw, b)["first_run"] is False
