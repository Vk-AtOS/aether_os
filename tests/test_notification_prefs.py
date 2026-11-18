"""KAN-159: a user can turn an event off and it stops appearing; the org default applies until a user overrides it;
the email channel asks the same settings; the default stays as today (everything on)."""
import asyncio
import time
import uuid

from aether_os.core import notification_prefs as prefs


def _note(gw, org, user_id, kind):
    gw.sql("INSERT INTO notifications (id, org_id, user_id, type, title, is_read, created_at) VALUES (?,?,?,?,?,0,?)",
           (str(uuid.uuid4()), org.org_id, user_id, kind, f"title {kind}", time.time()))


def _types(gw, who):
    return sorted(n["type"] for n in gw.client.get("/notifications", headers=who.auth).json()["items"])


def test_default_is_everything_on_and_turning_an_event_off_hides_it(gw):
    org = gw.register("prefone")
    _note(gw, org, org.user_id, "run_completed")
    _note(gw, org, org.user_id, "run_failed")
    got = gw.client.get("/notifications/preferences", headers=org.auth).json()["events"]
    assert {e["event"]: (e["in_app"], e["email"], e["source"]) for e in got} == {
        "run_completed": (True, True, "default"), "run_failed": (True, True, "default"),
        "approval_needed": (True, True, "default"), "approval_expiring": (True, True, "default"),
        "approval_expired": (True, True, "default"), "budget_alert": (True, True, "default")}
    assert _types(gw, org) == ["run_completed", "run_failed"]
    r = gw.client.put("/notifications/preferences", headers=org.auth, json={"event": "run_completed", "in_app": False})
    assert r.status_code == 200
    assert _types(gw, org) == ["run_failed"]
    assert asyncio.run(prefs.allows(org.org_id, org.user_id, "run_completed", "email")) is True
    assert gw.client.put("/notifications/preferences", headers=org.auth, json={"event": "nope", "email": False}).status_code == 422
    assert gw.client.put("/notifications/preferences", headers=org.auth, json={"event": "run_failed"}).status_code == 422


def test_email_channel_respects_the_setting(gw):
    org = gw.register("prefmail")
    gw.client.put("/notifications/preferences", headers=org.auth, json={"event": "run_failed", "email": False})
    assert asyncio.run(prefs.allows(org.org_id, org.user_id, "run_failed", "email")) is False
    assert asyncio.run(prefs.allows(org.org_id, org.user_id, "run_failed", "in_app")) is True


def test_org_default_is_admin_only_and_a_users_own_choice_wins(gw):
    org = gw.register("preforg")
    member = gw.user_with_role("member", org.org_id)
    body = {"event": "run_failed", "in_app": False}
    assert gw.client.put("/notifications/preferences/org", headers=member.auth, json=body).status_code == 403
    assert gw.client.put("/notifications/preferences/org", headers=org.auth, json=body).status_code == 200
    _note(gw, org, None, "run_failed")
    assert _types(gw, member) == []
    mine = gw.client.get("/notifications/preferences", headers=member.auth).json()["events"]
    assert [e["source"] for e in mine if e["event"] == "run_failed"] == ["org"]
    gw.client.put("/notifications/preferences", headers=member.auth, json={"event": "run_failed", "in_app": True})
    assert _types(gw, member) == ["run_failed"]
    # Another org is untouched by this org's default.
    other = gw.register("prefother")
    _note(gw, other, None, "run_failed")
    assert _types(gw, other) == ["run_failed"]
