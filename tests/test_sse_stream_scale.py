"""SSE stream: no gap between replay and live, keepalive when idle, closes on finished runs (KAN-136)."""
import asyncio
import json

import aether_os.core.audit.ledger as ledger_mod
import aether_os.core.pipeline_state as ps
import aether_os.gateway.auth_refresh as ar
import aether_os.gateway.routers.factory_run_streaming_router as rt


class FakeRedis:
    def __init__(self, items):
        self.items = [json.dumps(i) for i in items]

    def pubsub(self):

        class PS:
            async def subscribe(self, c):
                pass

            async def get_message(self, ignore_subscribe_messages=True, timeout=1):
                await asyncio.sleep(0.01)

            async def unsubscribe(self, c):
                pass

            async def aclose(self):
                pass
        return PS()

    async def lrange(self, key, a, b):
        return self.items[a:]


class Req:
    headers = {}

    async def is_disconnected(self):
        return False


class Ledger:
    def __init__(self, status):
        self.status = status

    async def async_get_run_detail(self, run_id, org_id=None):
        return {"id": run_id, "status": self.status}


def _setup(monkeypatch, redis, history, status="running"):
    async def pop(tok):
        return {"org_id": "o", "run_id": "r"}

    async def get_redis():
        return redis

    async def hist(run_id):
        return history

    monkeypatch.setattr(ar, "sse_token_pop", pop)
    monkeypatch.setattr(ps, "get_redis", get_redis)
    monkeypatch.setattr(ps, "get_event_history", hist)
    monkeypatch.setattr(ledger_mod, "get_ledger", lambda: Ledger(status))
    monkeypatch.setattr(rt, "POLL_S", 0.01)


async def _collect(resp, limit=50):
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


def test_event_published_between_replay_and_subscribe_is_not_lost(monkeypatch):
    first = [{"type": "phase_start", "n": 0}]
    r = FakeRedis(first + [{"type": "phase_start", "n": 1}, {"type": "pipeline_complete"}])
    _setup(monkeypatch, r, first)  # history read saw 1 event; 2 more landed before the loop started
    chunks = asyncio.run(_collect(asyncio.run(rt.stream_run_events("r", Req(), sse_token="t"))))
    data = [json.loads(c.split("data: ", 1)[1]) for c in chunks if "data: " in c]
    assert [d.get("n") for d in data if d["type"] == "phase_start"] == [0, 1]
    assert data[-1]["type"] == "pipeline_complete"
    assert "id: 2" in chunks[-1]


def test_finished_run_replays_then_closes(monkeypatch):
    hist = [{"type": "phase_start"}, {"type": "pipeline_complete"}]
    _setup(monkeypatch, FakeRedis(hist), hist)
    resp = asyncio.run(rt.stream_run_events("r", Req(), sse_token="t"))
    chunks = asyncio.run(_collect(resp))
    assert len(chunks) == 2  # finite: did not idle


def test_idle_stream_sends_keepalive_and_ends_when_run_finished_without_event(monkeypatch):
    _setup(monkeypatch, FakeRedis([]), [], status="completed")
    monkeypatch.setattr(rt, "KEEPALIVE_S", 0.05)
    chunks = asyncio.run(_collect(asyncio.run(rt.stream_run_events("r", Req(), sse_token="t"))))
    assert chunks[0].startswith(": keepalive")
    assert '"stream_end"' in chunks[-1]
