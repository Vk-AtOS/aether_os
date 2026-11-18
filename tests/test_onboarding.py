"""KAN-165: onboarding progress is derived from real data and follows the org across browsers; dismissal is org-wide, admin only."""


def _steps(gw, who):
    return {s["id"]: s["done"] for s in gw.client.get("/onboarding", headers=who.auth).json()["steps"]}


def test_steps_follow_real_data_and_dismissal_is_org_wide_and_admin_only(gw):
    org = gw.register("onb")
    gw.sql("UPDATE organisations SET name=? WHERE id=?", (org.email, org.org_id))   # what OAuth/SAML sign-up writes
    body = gw.client.get("/onboarding", headers=org.auth).json()
    assert body["dismissed"] is False and body["complete"] is False
    assert _steps(gw, org) == {"org_name": False, "dpa": False, "llm_key": False, "first_run": False, "invite_team": False, "plan": False, "sso": False}

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


def test_org_name_is_derived_from_the_row_and_dpa_is_stored_with_user_and_time(gw):
    org = gw.register("onbn")
    gw.sql("UPDATE organisations SET name=? WHERE id=?", (org.email.split("@")[0], org.org_id))   # sign-up with no name typed
    assert _steps(gw, org)["org_name"] is False          # sign-up named it after the owner's address
    gw.sql("UPDATE organisations SET name='Acme Pvt Ltd' WHERE id=?", (org.org_id,))
    got = _steps(gw, org)
    assert got["org_name"] is True and got["dpa"] is False

    member = gw.user_with_role("member", org.org_id)
    assert gw.client.post("/onboarding/dpa", headers=member.auth, json={"version": "1.0"}).status_code == 403
    assert gw.client.post("/onboarding/dpa", headers=org.auth, json={"version": "0.1"}).status_code == 409
    assert _steps(gw, org)["dpa"] is False
    assert gw.client.post("/onboarding/dpa", headers=org.auth, json={"version": "1.0"}).status_code == 200
    assert gw.client.post("/onboarding/dpa", headers=org.auth, json={"version": "1.0"}).status_code == 200   # idempotent
    rows = gw.sql("SELECT org_id, version, accepted_by, accepted_at FROM org_dpa_acceptance WHERE org_id=?", (org.org_id,))
    assert len(rows) == 1 and rows[0][1] == "1.0" and rows[0][2] and rows[0][3]
    assert _steps(gw, member)["dpa"] is True              # another person sees the organisation's answer
    assert _steps(gw, gw.register("onbo"))["dpa"] is False  # not another organisation's


def test_the_dpa_migration_follows_the_current_head():
    from pathlib import Path
    import re
    src = (Path(__file__).resolve().parent.parent / "alembic/versions/add_org_dpa_acceptance.py").read_text()
    assert re.search(r"down_revision[^=]*=\s*'add_webhook_outbox_quiet_hours'", src)
