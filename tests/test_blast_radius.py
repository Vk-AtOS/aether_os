"""KAN-52: the design table of scripts/fault_injection.py, checked in process against the real gateway.

Each test breaks one dependency the way it breaks in production and asserts which probes still answer. The compose version
(stop a container, probe) is scripts/fault_injection.py --run and needs Docker.
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.exc import OperationalError

import aether_os.gateway.auth_refresh as auth_refresh
from aether_os.core.resilience import health, reset_all
from aether_os.tests.gateway_env import gateway_env

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fault_injection", ROOT / "scripts/fault_injection.py")
fi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fi)

AUTHED = "/auth/my-orgs"
OK = {"status": "ok"}


def _state(r: httpx.Response) -> str:
    return "up" if r.status_code == 200 else "refused" if r.status_code in (502, 503, 504) else f"http {r.status_code}"


def _probe(gw):
    return {"healthz": _state(gw.client.get("/healthz")), "readyz": _state(gw.client.get("/readyz")),
            "authed read": _state(gw.client.get(AUTHED, headers=gw.auth)),
            "velaris": _state(gw.client.get("/velaris/agents", headers=gw.auth))}


@pytest.fixture
def env(monkeypatch):
    reset_all()
    monkeypatch.setenv("REQUIRE_REDIS", "true")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    yield
    reset_all()


def _expect(stopped, got):
    want = {p: v for p, v in fi.DESIGN[stopped].items() if p in got}
    assert got == want, f"stopping {stopped}: {got} but the design says {want}"


def test_design_table_is_what_the_docs_publish():
    assert fi.table() in (ROOT / "docs/ops/BLAST_RADIUS.md").read_text()


def test_nothing_stopped(tmp_path, env):
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=OK), \
            patch.object(health, "check_redis", return_value=OK), patch.object(auth_refresh, "_redis") as r:
        r.return_value.mget.return_value = [None, None, None]
        got = _probe(gw)
    got.pop("velaris")        # Velaris is not configured in this process: covered by its own test below
    _expect("(nothing)", got)


def test_redis_down_refuses_authenticated_calls_but_not_liveness(tmp_path, env):
    async def dead():
        raise ConnectionError("redis down")
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=OK), \
            patch.object(health, "check_redis", return_value={"status": "down"}), patch.object(auth_refresh, "_redis", dead):
        got = _probe(gw)
    got.pop("velaris")
    _expect("redis", got)


def test_postgres_down_is_unready_and_authenticated_calls_get_503_not_500(tmp_path, env):
    class Broken:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise OperationalError("connect", {}, ConnectionRefusedError("postgres down"))

        async def __aexit__(self, *a):
            return False

    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value={"status": "down"}), \
            patch.object(health, "check_redis", return_value=OK), patch.object(auth_refresh, "_redis") as r, \
            patch("aether_os.core.db.get_session_factory", lambda: Broken()):
        r.return_value.mget.return_value = [None, None, None]
        got = _probe(gw)
        retry = gw.client.get(AUTHED, headers=gw.auth).headers.get("retry-after")
    got.pop("velaris")
    _expect("db", got)
    assert retry == "5"


def test_velaris_down_only_takes_velaris_features_with_it(tmp_path, env, monkeypatch):
    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setenv("VELARIS_API_URL", "http://127.0.0.1:1")           # nothing listens: connection refused
    monkeypatch.setenv("VELARIS_API_SECRET", "s" * 32)
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY_PEM", pem)
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=OK), \
            patch.object(health, "check_redis", return_value=OK), patch.object(auth_refresh, "_redis") as r:
        r.return_value.mget.return_value = [None, None, None]
        for _ in range(6):                                                 # past the breaker threshold
            gw.client.get("/velaris/agents", headers=gw.auth)
        got = _probe(gw)
        ready = gw.client.get("/readyz").json()
    _expect("velaris", got)
    assert ready == {"ready": True, "degraded": ["velaris"]}               # the dashboard names the degraded component


def test_llm_down_does_not_touch_guards_or_approvals(tmp_path, env):
    from aether_os.core.errors import LLMUnavailable

    async def no_model(*a, **k):
        raise LLMUnavailable("every provider is down")
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=OK), \
            patch.object(health, "check_redis", return_value=OK), patch.object(auth_refresh, "_redis") as r, \
            patch("aether_os.core.model_router.ModelRouter.call", no_model):
        r.return_value.mget.return_value = [None, None, None]
        assert gw.client.get("/prime/inbox", headers=gw.auth).status_code == 200      # approvals
        assert gw.client.get(AUTHED, headers=gw.auth).status_code == 200
        assert gw.client.get("/readyz").status_code == 200
