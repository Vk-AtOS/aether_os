"""KAN-160: platform-wide routes are for the platform operator (superadmin); an org owner/admin gets 403 (D7).
The cleanup route changes runs, so it must touch only the caller's own org."""
import pytest

READ_ROUTES = ["/admin/error-registry", "/admin/error-registry/summary", "/admin/platform-health",
               "/system/feature-flags", "/system/workloop"]


@pytest.mark.parametrize("path", READ_ROUTES)
def test_org_admin_member_get_403_superadmin_is_let_in(gw, path):
    org = gw.register("opsroles")
    admin = gw.user_with_role("admin", org.org_id)
    member = gw.user_with_role("member", org.org_id)
    root = gw.user_with_role("superadmin", org.org_id)
    assert gw.client.get(path, headers=org.auth).status_code == 403  # owner of an ordinary org
    assert gw.client.get(path, headers=admin.auth).status_code == 403
    assert gw.client.get(path, headers=member.auth).status_code == 403
    assert gw.client.get(path, headers=root.auth).status_code == 200


def test_cleanup_council_review_only_touches_the_callers_org(gw):
    a, b = gw.register("cleana"), gw.register("cleanb")
    for org, rid in ((a, "stuck-a"), (b, "stuck-b")):
        gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
               "VALUES (?, ?, 'x', 'council_review', 0, 0, 1)", (rid, org.org_id))
    assert gw.client.post("/admin/runs/cleanup-council-review", headers=a.auth).json()["promoted"] == 1
    # KAN-247: a run whose final verdict never got written is not reported as completed.
    assert gw.sql("SELECT status FROM runs WHERE id='stuck-a'")[0][0] == "needs_review"
    assert gw.sql("SELECT status FROM runs WHERE id='stuck-b'")[0][0] == "council_review"


def test_org_quality_metrics_do_not_carry_the_platform_error_registry(gw):
    org = gw.register("qmetrics")
    root = gw.user_with_role("superadmin", org.org_id)
    assert gw.client.get("/admin/platform/quality-metrics", headers=org.auth).json()["top_error_categories"] == []
    assert gw.client.get("/admin/platform/quality-metrics", headers=root.auth).status_code == 200
