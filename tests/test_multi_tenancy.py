import pytest
import uuid
import httpx
from fastapi.testclient import TestClient
from aether_os.gateway.api import create_app
from aether_os.core.db import get_session_factory, Base, get_engine
from aether_os.core.models import Organisation, User, Run

@pytest.fixture
async def client():
    app = create_app()
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    
    from aether_os.core.db import init_db
    await init_db()
    
    with TestClient(app) as c:
        yield c

@pytest.mark.asyncio
async def test_multi_tenancy_workflow():
    app = create_app()
    # Use a fresh in-memory DB for testing
    import os
    import aether_os.core.db
    aether_os.core.db._engine = None
    aether_os.core.db._session_factory = None
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-12345678901234567890"
    
    from aether_os.core.db import init_db
    await init_db()
    
    with TestClient(app) as client:
        # 1. Register Org A
        email_a = f"owner_a_{uuid.uuid4()}@test.com"
        resp = client.post("/auth/register", json={
            "email": email_a,
            "password": "password123",
            "org_name": "Org A"
        })
        assert resp.status_code == 200
        data_a = resp.json()
        token_a = data_a["access_token"]
        
        # 2. Register Org B
        email_b = f"owner_b_{uuid.uuid4()}@test.com"
        resp = client.post("/auth/register", json={
            "email": email_b,
            "password": "password123",
            "org_name": "Org B"
        })
        assert resp.status_code == 200
        data_b = resp.json()
        token_b = data_b["access_token"]
        
        # 3. Org A starts 3 runs
        for i in range(3):
            resp = client.post("/factory/start", 
                json={"requirement": f"Run {i} for Org A"},
                headers={"Authorization": f"Bearer {token_a}"}
            )
            assert resp.status_code == 200
        
        # 4. Org A tries 4th run -> 402
        resp = client.post("/factory/start", 
            json={"requirement": "Run 4 for Org A"},
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert resp.status_code == 402
        assert resp.json()["detail"]["error"] == "trial_limit_reached"
        
        # 5. Check isolation: Org B should have 0 runs
        resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {token_b}"})
        assert resp.status_code == 200
        assert len(resp.json()) == 0
        
        # 6. Org B starts a run
        resp = client.post("/factory/start", 
            json={"requirement": "Run 1 for Org B"},
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert resp.status_code == 200
        
        # 7. Check isolation: Org A should see 3 runs
        resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200
        assert len(resp.json()) == 3
        
        # 8. API Key Auth
        resp = client.post("/auth/api-keys", 
            json={"name": "test-key"},
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert resp.status_code == 200
        api_key = resp.json()["api_key"]
        
        resp = client.get("/factory/runs", headers={"Authorization": f"Bearer {api_key}"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # 9. Usage endpoint
        resp = client.get("/account/usage", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200
        usage = resp.json()
        assert usage["runs_used"] == 3
        assert usage["runs_remaining"] == 0
        print("\n✅ Multi-tenancy and Trial limit verification PASSED")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_multi_tenancy_workflow())
