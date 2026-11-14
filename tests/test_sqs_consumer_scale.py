"""SQS consumer: bounded in-flight jobs, poison messages dead-lettered, blocking calls off the loop."""
import asyncio

import aether_os.core.queue.pipeline_consumer as pc
import aether_os.core.queue.sqs_client as sq


def _job(i, count=1):
    return {"run_id": f"r{i}", "params": {}, "receipt_handle": f"h{i}", "receive_count": count, "body": "{}"}


def test_backpressure_never_exceeds_max_inflight(monkeypatch):
    monkeypatch.setenv("SQS_MAX_INFLIGHT", "2")
    monkeypatch.setattr(sq, "is_enabled", lambda: True)
    queue = [_job(i) for i in range(6)]
    running, peak = [0], [0]

    def receive(n, w):
        return [queue.pop(0)] if queue else []

    async def execute(run_id, params, handle):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.05)
        running[0] -= 1

    monkeypatch.setattr(sq, "receive_jobs", receive)
    monkeypatch.setattr(pc, "_execute_job", execute)

    async def go():
        pc._RUNNING = True
        t = asyncio.create_task(pc._poll_loop())
        await asyncio.sleep(0.6)
        pc._RUNNING = False
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    assert peak[0] == 2
    assert not queue  # all six were eventually processed


def test_poison_message_is_dead_lettered_not_retried(monkeypatch):
    monkeypatch.setenv("SQS_DLQ_URL", "dlq")
    calls = {"dlq": [], "del": [], "failed": []}
    monkeypatch.setattr(sq, "send_to_dlq", lambda body, reason: calls["dlq"].append(body) or True)
    monkeypatch.setattr(sq, "delete_job", lambda h: calls["del"].append(h))

    async def mark(run_id, msg):
        calls["failed"].append(run_id)

    monkeypatch.setattr(pc, "_mark_failed", mark)
    asyncio.run(pc._park_poison(_job(1, count=pc.MAX_RECEIVES + 1)))
    assert calls == {"dlq": ["{}"], "del": ["h1"], "failed": ["r1"]}


def test_poison_message_kept_when_dlq_send_fails(monkeypatch):
    monkeypatch.setenv("SQS_DLQ_URL", "dlq")
    deleted = []
    monkeypatch.setattr(sq, "send_to_dlq", lambda b, r: False)
    monkeypatch.setattr(sq, "delete_job", lambda h: deleted.append(h))

    async def mark(*a):
        pass

    monkeypatch.setattr(pc, "_mark_failed", mark)
    asyncio.run(pc._park_poison(_job(2, count=9)))
    assert deleted == []  # never drop the only copy
