"""KAN-159: quiet hours (e-mail held back, approvals exempt) and the budget-alert preference."""
import asyncio
import time
import uuid
from datetime import datetime, timezone

from aether_os.core import notification_prefs as prefs


def at(h, m=0):
    return datetime(2026, 11, 17, h, m, tzinfo=timezone.utc)


def test_window_logic_wraps_midnight_and_handles_zones():
    assert prefs.in_quiet(22 * 60, 7 * 60, "UTC", at(23)) and prefs.in_quiet(22 * 60, 7 * 60, "UTC", at(6, 59))
    assert not prefs.in_quiet(22 * 60, 7 * 60, "UTC", at(7)) and not prefs.in_quiet(22 * 60, 7 * 60, "UTC", at(12))
    assert not prefs.in_quiet(600, 600, "UTC", at(10))                      # start == end: no window
    assert prefs.in_quiet(22 * 60, 7 * 60, "Asia/Kolkata", at(17))          # 22:30 in Kolkata
    assert prefs.in_quiet(0, 60, "No/Such_Zone", at(0, 30))                  # unknown zone = UTC, never an exception


def test_quiet_hours_hold_email_but_not_in_app_or_approvals(gw):
    org = gw.register("quiet")
    r = gw.client.put("/notifications/quiet-hours", headers=org.auth, json={"start": "22:00", "end": "07:00", "tz": "UTC"})
    assert r.status_code == 200 and r.json()["quiet_hours"] == {"start": "22:00", "end": "07:00", "tz": "UTC", "source": "user"}
    night, day = at(23), at(12)
    run = lambda ev, ch, now: asyncio.run(prefs.allows(org.org_id, org.user_id, ev, ch, now))  # noqa: E731
    assert run("run_failed", "email", night) is False and run("run_failed", "email", day) is True
    assert run("run_failed", "in_app", night) is True
    assert run("approval_expiring", "email", night) is True      # an approval must not expire unseen
    assert gw.client.put("/notifications/quiet-hours", headers=org.auth, json={"start": "25:00", "end": "07:00"}).status_code == 422
    assert gw.client.put("/notifications/quiet-hours", headers=org.auth, json={"start": "22:00", "end": "07:00", "tz": "Mars/Base"}).status_code == 422


def test_org_default_applies_until_the_user_sets_their_own_and_only_admins_set_it(gw):
    org = gw.register("quietorg")
    member = gw.user_with_role("member", org.org_id)
    body = {"start": "20:00", "end": "08:00", "tz": "UTC"}
    assert gw.client.put("/notifications/quiet-hours/org", headers=member.auth, json=body).status_code == 403
    assert gw.client.put("/notifications/quiet-hours/org", headers=org.auth, json=body).status_code == 200
    got = gw.client.get("/notifications/quiet-hours", headers=member.auth).json()["quiet_hours"]
    assert got["source"] == "org" and got["start"] == "20:00"
    gw.client.put("/notifications/quiet-hours", headers=member.auth, json={"start": "01:00", "end": "02:00", "tz": "UTC"})
    assert gw.client.get("/notifications/quiet-hours", headers=member.auth).json()["quiet_hours"]["source"] == "user"
    other = gw.register("quietother")
    assert gw.client.get("/notifications/quiet-hours", headers=other.auth).json()["quiet_hours"] is None


def test_budget_alert_preference_hides_the_80_percent_notice(gw):
    org = gw.register("budgetpref")
    gw.sql("INSERT INTO notifications (id, org_id, user_id, type, title, is_read, created_at) VALUES (?,?,?,?,?,0,?)",
           (str(uuid.uuid4()), org.org_id, None, "llm_budget_80:2026-11", "AI usage at 80%", time.time()))
    types = lambda: [n["type"] for n in gw.client.get("/notifications", headers=org.auth).json()["items"]]  # noqa: E731
    assert types() == ["llm_budget_80:2026-11"]
    gw.client.put("/notifications/preferences", headers=org.auth, json={"event": "budget_alert", "in_app": False})
    assert types() == []
