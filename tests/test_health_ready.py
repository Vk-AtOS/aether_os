"""KAN-47/49: liveness vs readiness, the degraded-component view and the dead-letter window."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from aether_os.tests.gateway_env import gateway_env
import aether_os.gateway.routers.ops_status_router as ops
from aether_os.core.resilience import health


def test_healthz_never_touches_dependencies(tmp_path):
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", side_effect=AssertionError("probed")):
        r = gw.client.get("/healthz")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_is_503_when_postgres_is_down_and_names_it(tmp_path):
    down = {"status": "down", "error": "OperationalError"}
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=down):
        r = gw.client.get("/readyz")
        assert r.status_code == 503
        assert r.json() == {"ready": False, "degraded": ["postgres"]}      # names only, no error detail


def test_redis_down_is_degraded_not_unready_unless_required(tmp_path, monkeypatch):
    ok, down = {"status": "ok"}, {"status": "down", "error": "ConnectionError"}
    monkeypatch.delenv("REQUIRE_REDIS", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with gateway_env(tmp_path) as gw, patch.object(health, "check_postgres", return_value=ok), \
            patch.object(health, "check_redis", return_value=down):
        r = gw.client.get("/readyz")
        assert r.status_code == 200 and r.json() == {"ready": True, "degraded": ["redis"]}
        monkeypatch.setenv("REQUIRE_REDIS", "true")
        assert gw.client.get("/readyz").status_code == 503                  # then rate limits cannot be trusted


def test_open_velaris_breaker_shows_as_degraded_and_does_not_make_api_unready(monkeypatch):
    from aether_os.core.resilience import get_breaker
    monkeypatch.setenv("VELARIS_API_URL", "http://velaris.invalid:8730")
    b = get_breaker("velaris", failure_threshold=1)
    b.record_failure("timeout")
    try:
        async def go():
            with patch.object(health, "check_postgres", return_value={"status": "ok"}), \
                    patch.object(health, "check_redis", return_value={"status": "ok"}):
                return await health.snapshot()
        snap = asyncio.run(go())
        assert snap["ready"] is True and snap["degraded"] == ["velaris"]
    finally:
        b.record_success()


def test_components_endpoint_requires_admin():
    with pytest.raises(HTTPException) as e:
        ops._admin({"role": "member", "org_id": "o"})
    assert e.value.status_code == 403
    assert ops._admin({"role": "admin", "org_id": "o"})["role"] == "admin"


def test_dead_letters_of_other_organisations_are_not_shown():
    items = [{"run_id": "mine", "reason": "r"}, {"run_id": "theirs", "reason": "r"}]

    class Res:
        def scalars(self):
            return iter(["mine"])

    class Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            assert "org_id" in str(stmt)          # the lookup is scoped to the caller's organisation
            return Res()

    with patch.object(ops, "peek_dlq", return_value=items), patch.object(ops, "dlq_depth", return_value=57), \
            patch.object(ops, "get_session_factory", return_value=lambda: Sess()), \
            patch.object(ops.outbox, "dead_letters", new=AsyncMock(return_value=[])):
        mine = asyncio.run(ops.dead_letters({"role": "admin", "org_id": "o1"}))
        allq = asyncio.run(ops.dead_letters({"role": "superadmin", "org_id": "o0"}))
    assert [i["run_id"] for i in mine["items"]] == ["mine"] and mine["depth"] == 1
    assert allq["depth"] == 57 and len(allq["items"]) == 2
