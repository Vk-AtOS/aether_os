"""KAN-102 item 7: webhook deliveries survive a restart, are retried with backoff, bounded, then dead-lettered."""
import asyncio
import types

from aether_os.core.webhooks import delivery, outbox


def _hook(gw, org):
    r = gw.client.post("/webhooks", json={"url": "https://hooks.example.org/in", "events": []}, headers=org.auth)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _fake_http(monkeypatch, codes):
    sent = []

    async def fake(method, url, content=None, headers=None, timeout=None):
        sent.append(headers["X-AetherOS-Delivery"])
        return types.SimpleNamespace(status_code=codes.pop(0) if codes else 200)
    monkeypatch.setattr(delivery, "safe_request", fake)
    return sent


def _rows(gw, org):
    return gw.sql("SELECT status, attempts, next_attempt_at FROM webhook_outbox WHERE org_id = ?", (org.org_id,))


def _drain(gw):
    async def go():
        for t in list(delivery._tasks):
            await t
    gw.client.portal.call(go)


def test_a_failed_delivery_is_kept_and_retried_after_a_restart(gw, monkeypatch):
    org = gw.register("whout")
    _hook(gw, org)
    sent = _fake_http(monkeypatch, [503])
    gw.client.portal.call(delivery.deliver_event, org.org_id, "pipeline.complete", {"a": 1})
    _drain(gw)
    status, attempts, due = _rows(gw, org)[0]
    assert (status, attempts) == ("pending", 1) and due > __import__("time").time()   # backed off, not lost
    # "restart": nothing in memory knows about it any more; the sweeper finds it in the table once it is due
    delivery._tasks.clear()
    gw.sql("UPDATE webhook_outbox SET next_attempt_at = 0 WHERE org_id = ?", (org.org_id,))
    assert gw.client.portal.call(outbox.sweep_once) >= 1
    assert _rows(gw, org)[0][:2] == ("done", 2)
    assert len(sent) == 2 and len(set(sent)) == 1          # same delivery id, so the receiver can de-duplicate


def test_retries_are_bounded_then_dead_lettered_and_shown_to_that_org_only(gw, monkeypatch):
    org, other = gw.register("whdead"), gw.register("whother")
    _hook(gw, org)
    _fake_http(monkeypatch, [500] * 50)
    gw.client.portal.call(delivery.deliver_event, org.org_id, "pipeline.complete", {})
    _drain(gw)
    for _ in range(outbox.MAX_ATTEMPTS + 2):
        gw.sql("UPDATE webhook_outbox SET next_attempt_at = 0 WHERE org_id = ? AND status = 'pending'", (org.org_id,))
        gw.client.portal.call(outbox.sweep_once)
    status, attempts, _due = _rows(gw, org)[0]
    assert (status, attempts) == ("dead", outbox.MAX_ATTEMPTS)
    admin = gw.client.get("/system/dead-letters", headers=org.auth)
    assert admin.status_code == 200, admin.text
    mine = admin.json()["webhooks"]
    assert len(mine) == 1 and mine[0]["error"] == "HTTP 500" and "payload" not in mine[0]
    assert gw.client.get("/system/dead-letters", headers=other.auth).json()["webhooks"] == []


def test_two_workers_never_send_the_same_attempt_twice(gw, monkeypatch):
    org = gw.register("whclaim")
    _hook(gw, org)
    sent = _fake_http(monkeypatch, [])
    gw.client.portal.call(delivery.deliver_event, org.org_id, "pipeline.complete", {})
    _drain(gw)
    gw.sql("UPDATE webhook_outbox SET status = 'pending', attempts = 0, next_attempt_at = 0 WHERE org_id = ?", (org.org_id,))
    sent.clear()
    row_id = gw.sql("SELECT id FROM webhook_outbox WHERE org_id = ?", (org.org_id,))[0][0]

    async def two():
        return await asyncio.gather(outbox.attempt_row(row_id), outbox.attempt_row(row_id))
    assert sorted(gw.client.portal.call(two)) == [False, True]
    assert len(sent) == 1


def test_removed_webhook_dead_letters_instead_of_retrying_forever(gw, monkeypatch):
    org = gw.register("whgone")
    hid = _hook(gw, org)
    _fake_http(monkeypatch, [500])
    gw.client.portal.call(delivery.deliver_event, org.org_id, "pipeline.complete", {})
    _drain(gw)
    gw.sql("UPDATE webhooks SET is_active = 0 WHERE id = ?", (hid,))
    gw.sql("UPDATE webhook_outbox SET next_attempt_at = 0 WHERE org_id = ?", (org.org_id,))
    gw.client.portal.call(outbox.sweep_once)
    assert _rows(gw, org)[0][0] == "dead"
