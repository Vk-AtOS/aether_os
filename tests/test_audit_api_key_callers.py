"""KAN-101: mutating calls made with an API key are audited too (the middleware only decoded JWTs)."""
import time


def test_api_key_mutation_is_audited_under_its_org(gw):
    a = gw.register("auditor")
    key = gw.client.post("/auth/api-keys", headers=a.auth, json={"name": "k"}).json()
    secret = key.get("key") or key.get("api_key")
    assert secret
    r = gw.client.post("/webhooks", headers={"Authorization": f"Bearer {secret}"},
                       json={"url": "https://example.com/audit-probe", "events": []})
    assert r.status_code < 500
    rows = []
    for _ in range(50):
        rows = gw.sql("SELECT org_id, user_id FROM audit_log WHERE action = 'POST /webhooks' AND org_id = ?", (a.org_id,))
        if rows:
            break
        time.sleep(0.1)
    assert rows and rows[0][1].startswith("api_key:")
