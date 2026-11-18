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


# ── KAN-131: no plaintext credentials in generated gateway / queue config ─────────────────────
def test_kong_config_has_a_jwt_consumer_template_with_the_key_from_the_environment():
    import yaml
    from aether_os.core.cloud_primitives.gateway import generate_kong_declarative_config
    text = generate_kong_declarative_config([{"name": "api", "port": 8000}], "my-app")
    cfg = yaml.safe_load(text)
    consumer = cfg["consumers"][0]                     # was [] : every call through the gateway was a 401
    secret = consumer["jwt_secrets"][0]
    assert secret["algorithm"] == "RS256"
    assert secret["rsa_public_key"].startswith("{vault://env/")        # referenced, never inlined
    assert "BEGIN" not in text


def test_nats_compose_takes_credentials_from_the_environment_and_binds_localhost():
    from aether_os.core.cloud_primitives.queue import generate_nats_docker_compose
    text = generate_nats_docker_compose("my-app")
    assert "${NATS_USER:?" in text and "${NATS_PASSWORD:?" in text and "--user ${NATS_USER}" in text
    assert '"4222:4222"' not in text and '"127.0.0.1:4222:4222"' in text   # was open on every interface, no auth


# ── KAN-131: cell planner and capacity planner review ─────────────────────────────────────────
def test_cell_health_queue_check_runs_and_does_not_block():
    import asyncio
    from aether_os.core.cell_architecture.cell_planner import generate_cell_health_check
    ns: dict = {}
    exec(compile(generate_cell_health_check("my-app"), "cell_health.py", "exec"), ns)   # noqa: S102

    async def go():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        import os
        os.environ["KAFKA_BROKERS"] = f"127.0.0.1:{port}"
        try:
            up = await ns["_check_queue"]()          # was a NameError (socket never imported) -> always False
        finally:
            server.close()
            await server.wait_closed()
        os.environ["KAFKA_BROKERS"] = "127.0.0.1:1"
        return up, await ns["_check_queue"]()
    up, down = asyncio.run(go())
    assert up is True and down is False


def test_global_accelerator_groups_are_each_dialled_to_100():
    from aether_os.core.cell_architecture.cell_planner import generate_cell_terraform
    tf = generate_cell_terraform("my-app", ["us-east-1", "eu-west-1", "ap-southeast-1"])
    assert tf.count("traffic_dial_percentage = 100") == 3      # was 33 each: 1/3 of the traffic per group


def test_pdb_never_blocks_a_single_replica_drain():
    from aether_os.core.capacity_planner.planner import generate_pdb
    assert "maxUnavailable: 1" in generate_pdb("svc", "ns", "batch")        # was minAvailable 50% of 1 replica = 1
    assert 'minAvailable: "67%"' in generate_pdb("svc", "ns", "real_time")
