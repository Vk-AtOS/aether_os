"""KAN-69 F15: /system/metrics is for signed-in callers; host load and the platform-wide run count are superadmin only."""


def test_metrics_need_a_token_and_hide_host_load_from_a_member(gw):
    assert gw.client.get("/system/metrics").status_code == 401
    org = gw.register("metricsorg")
    body = gw.client.get("/system/metrics", headers=org.auth).json()
    assert body["cpu_percent"] is None and body["memory_percent"] is None and body["disk_percent"] is None
    assert body["active_runs"] == 0
    root = gw.user_with_role("superadmin", org.org_id)
    assert gw.client.get("/system/metrics", headers=root.auth).json()["cpu_percent"] is not None


def test_zero_trust_probe_failure_does_not_echo_the_exception(gw, monkeypatch):
    monkeypatch.setenv("AETHER_ONE_ZT_SECRET", "x" * 40)
    from aether_os.core.identity import zero_trust

    def boom(*a, **k):
        raise RuntimeError("secret internals /srv/key.pem")
    monkeypatch.setattr(zero_trust, "issue_ticket", boom)
    body = gw.client.get("/health/zero-trust").json()
    assert body["status"] == "degraded" and "internals" not in str(body)
