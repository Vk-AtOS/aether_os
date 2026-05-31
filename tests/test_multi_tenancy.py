import pytest
import uuid
import os
import asyncio
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from aether_os.gateway.api import create_app


@pytest.mark.asyncio
async def test_multi_tenancy_workflow(tmp_path):
    import aether_os.core.db as _db_mod
    import aether_os.core.rate_limiter as _rl_mod

    # File-based SQLite — each connection sees the same data (unlike :memory:)
    _db_mod._engine = None
    _db_mod._session_factory = None

    # Force rate limiter into in-memory mode — Redis state accumulates across runs
    _rl_mod._mem = _rl_mod._MemoryStore()
    _rl_mod._instance = None
    _rl_mod._redis_available = False
    _rl_mod._async_redis_client = None
    old_db = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/mt_test.db"
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-12345678901234567890"
    os.environ["PIPELINE_TIMEOUT_MINUTES"] = "0.05"  # 3-second limit

    async def _fake_pipeline_run(
        self, client_id="", raw_input="", domain="general",
        project_name=None, start_phase=None, run_id=None,
        org_id=None, org_slug=None, plan=None,
        is_change_request=False, memory_context=None,
        council_preflight=None,
    ):
        import time as _time
        from aether_os.core.db import get_session_factory as _gsf
        from aether_os.core.models import Run as _Run
        _sf = _gsf()
        async with _sf() as _s:
            _s.add(_Run(
                id=run_id or str(uuid.uuid4()),
                org_id=org_id,
                command=f"factory: {raw_input[:60]}",
                status="completed",
                started_at=_time.time(),
            ))
            await _s.commit()
        return {"run_id": run_id, "status": "completed"}

    from aether_os.orchestrator.factory_pipeline import FactoryPipeline

    try:
        with patch.object(FactoryPipeline, "run", _fake_pipeline_run), \
             patch("aether_os.core.guardian.password_shield.check_password_safety",
                   new_callable=AsyncMock, return_value=(True, "")), \
             TestClient(create_app()) as client:

            # 1. Register Org A
            email_a = f"owner_a_{uuid.uuid4()}@test.com"
            resp = client.post("/auth/register", json={
                "email": email_a,
                "password": "TestPass@123!",
                "org_name": "Org A",
                "terms_accepted": True,
                "dpa_accepted": True,
            })
            assert resp.status_code == 200, resp.text
            token_a = resp.json()["access_token"]

            # 2. Register Org B
            email_b = f"owner_b_{uuid.uuid4()}@test.com"
            resp = client.post("/auth/register", json={
                "email": email_b,
                "password": "TestPass@123!",
                "org_name": "Org B",
                "terms_accepted": True,
                "dpa_accepted": True,
            })

            assert resp.status_code == 200, resp.text
            token_b = resp.json()["access_token"]

            # 3. Org A starts 3 runs (trial limit = 3)
            for i in range(3):
                resp = client.post(
                    "/factory/start",
                    json={"requirement": f"Run {i} for Org A"},
                    headers={"Authorization": f"Bearer {token_a}"},
                )
                assert resp.status_code == 200, f"Run {i}: {resp.text}"

            # 4. Org A 4th run → 402 trial limit
            resp = client.post(
                "/factory/start",
                json={"requirement": "Run 4 for Org A"},
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert resp.status_code == 402, resp.text
            assert resp.json()["detail"]["error"] == "trial_limit_reached"

            # 5. Org B sees 0 runs (isolation)
            resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {token_b}"})
            assert resp.status_code == 200
            data = resp.json()
            if isinstance(data, list):
                assert len(data) == 0
            else:
                assert data["total"] == 0
            # 6. Org B starts a run
            resp = client.post(
                "/factory/start",
                json={"requirement": "Run 1 for Org B"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert resp.status_code == 200, resp.text

            # 7. Org A sees exactly 3 runs
            resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {token_a}"})
            assert resp.status_code == 200
            data = resp.json()
            if isinstance(data, list):
                assert len(data) == 3
            else:
                assert data["total"] == 3
            # 8. API key auth
            resp = client.post(
                "/auth/api-keys",
                json={"name": "test-key"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert resp.status_code == 200
            api_key = resp.json()["api_key"]

            resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {api_key}"})
            assert resp.status_code == 200
            data = resp.json()
            if isinstance(data, list):
                assert len(data) == 1
            else:
                assert data["total"] == 1
            # 9. Usage endpoint
            resp = client.get("/account/usage", headers={"Authorization": f"Bearer {token_a}"})
            assert resp.status_code == 200
            usage = resp.json()
            assert usage["runs_used"] == 3
            assert usage["runs_remaining"] == 0

    finally:
        _db_mod._engine = None
        _db_mod._session_factory = None
        if old_db is not None:
            os.environ["DATABASE_URL"] = old_db
        else:
            os.environ.pop("DATABASE_URL", None)
        os.environ.pop("PIPELINE_TIMEOUT_MINUTES", None)
