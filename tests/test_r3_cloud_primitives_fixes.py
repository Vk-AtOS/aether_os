"""KAN-131: generated NATS streams do not overlap, failed messages reach the DLQ, Kong has no wildcard-credentials CORS."""
import asyncio
import sys
import types

import yaml

from aether_os.core.cloud_primitives.gateway import generate_kong_declarative_config
from aether_os.core.cloud_primitives.queue import generate_python_queue_client, generate_stream_config


def _overlap(a: str, b: str) -> bool:
    """NATS subject overlap for the patterns used here (tokens, '>' = the rest)."""
    ta, tb = a.split("."), b.split(".")
    for x, y in zip(ta, tb):
        if x == ">" or y == ">":
            return True
        if x != y and "*" not in (x, y):
            return False
    return len(ta) == len(tb)


def test_dead_letter_stream_subjects_do_not_overlap_the_main_stream():
    main, dlq = yaml.safe_load(generate_stream_config("order", "shop"))["streams"]
    # JetStream refuses to create a stream whose subjects overlap another stream's: the DLQ never existed
    assert not any(_overlap(m, d) for m in main["subjects"] for d in dlq["subjects"])


class _Msg:
    def __init__(self, delivered):
        self.data, self.metadata = b'{"a": 1}', types.SimpleNamespace(num_delivered=delivered)
        self.calls = []

    async def ack(self): self.calls.append("ack")
    async def term(self): self.calls.append("term")
    async def nak(self, delay=None): self.calls.append(("nak", delay))


def _client(monkeypatch):
    nats = types.ModuleType("nats")
    mods = {"nats": nats, "nats.aio": types.ModuleType("nats.aio"), "nats.aio.client": types.ModuleType("nats.aio.client"),
            "nats.js": types.ModuleType("nats.js"), "nats.js.api": types.ModuleType("nats.js.api")}
    mods["nats.aio.client"].Client = object
    mods["nats.js"].JetStreamContext = object
    mods["nats.js.api"].AckPolicy = types.SimpleNamespace(EXPLICIT="explicit")
    mods["nats.js.api"].ConsumerConfig = lambda **kw: kw
    for k, v in mods.items():
        monkeypatch.setitem(sys.modules, k, v)
    ns = {"__name__": "queue_client"}
    exec(compile(generate_python_queue_client([{"table": "order"}]), "queue_client.py", "exec"), ns)
    return ns


def test_failed_message_is_nacked_with_backoff_then_parked_in_the_dlq(monkeypatch):
    ns = _client(monkeypatch)
    published, subs = [], {}

    class JS:
        async def publish(self, subject, data, headers=None):
            published.append((subject, data, headers))

        async def subscribe(self, subject, **kw):
            subs.update(kw)

    c = ns["QueueClient"]()
    c._js = JS()

    async def boom(_):
        raise ValueError("bad")

    asyncio.run(c.subscribe("order", "created", boom))
    assert subs["manual_ack"] is True and subs["config"]["max_deliver"] == 5
    early, last = _Msg(2), _Msg(5)
    asyncio.run(subs["cb"](early))
    assert early.calls == [("nak", 4)] and not published
    asyncio.run(subs["cb"](last))
    assert last.calls == ["term"] and published[0][0] == "app.dlq.order.created" and published[0][1] == b'{"a": 1}'


def test_kong_has_no_wildcard_cors_with_credentials_and_redis_rate_limit_when_configured():
    plain = yaml.safe_load(generate_kong_declarative_config([{"name": "api", "port": 8000}], "x"))
    assert [p["name"] for p in plain["plugins"]] == ["rate-limiting", "jwt"]       # no cors plugin without origins
    assert plain["plugins"][0]["config"]["policy"] == "local"
    full = yaml.safe_load(generate_kong_declarative_config(
        [{"name": "api", "port": 8000}], "x", cors_origins=["https://app.example"], redis_host="redis"))
    cors = next(p for p in full["plugins"] if p["name"] == "cors")["config"]
    assert cors["origins"] == ["https://app.example"] and "*" not in str(cors["origins"])
    rl = full["plugins"][0]["config"]
    assert rl["policy"] == "redis" and rl["redis_host"] == "redis"


def test_litmus_rbac_is_namespaced_and_cannot_touch_secrets_or_nodes():
    from aether_os.core.chaos_engineering.chaos_generator import generate_litmus_rbac
    docs = [d for d in yaml.safe_load_all(generate_litmus_rbac("shop")) if d]
    kinds = [d["kind"] for d in docs]
    assert kinds == ["ServiceAccount", "Role", "RoleBinding"]      # was ClusterRole + ClusterRoleBinding
    resources = {r for rule in docs[1]["rules"] for r in rule["resources"]}
    assert not resources & {"secrets", "nodes"}
    assert all(d["metadata"]["namespace"] == "shop" for d in docs)
