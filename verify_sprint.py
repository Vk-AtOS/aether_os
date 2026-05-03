import httpx
import asyncio
import uuid

BASE_URL = "http://localhost:8080"

async def test_multi_tenancy():
    async with httpx.AsyncClient() as client:
        # 1. Register Org A
        org_a_email = f"user_a_{uuid.uuid4().hex[:4]}@test.com"
        resp = await client.post(f"{BASE_URL}/auth/register", json={
            "email": org_a_email,
            "password": "password123",
            "org_name": "Org A"
        })
        print(f"Register Org A: {resp.status_code}")
        org_a_token = resp.json()["access_token"]
        org_a_id = resp.json()["org_id"]

        # 2. Register Org B
        org_b_email = f"user_b_{uuid.uuid4().hex[:4]}@test.com"
        resp = await client.post(f"{BASE_URL}/auth/register", json={
            "email": org_b_email,
            "password": "password123",
            "org_name": "Org B"
        })
        print(f"Register Org B: {resp.status_code}")
        org_b_token = resp.json()["access_token"]
        org_b_id = resp.json()["org_id"]

        # 3. Start run for Org A
        headers_a = {"Authorization": f"Bearer {org_a_token}"}
        resp = await client.post(f"{BASE_URL}/factory/start", headers=headers_a, json={
            "requirement": "Test requirement for Org A"
        })
        print(f"Start Run Org A: {resp.status_code}")
        run_a_id = resp.json()["run_id"]

        # 4. Check if Org B can see Org A's run
        headers_b = {"Authorization": f"Bearer {org_b_token}"}
        resp = await client.get(f"{BASE_URL}/factory/runs/{run_a_id}", headers=headers_b)
        print(f"Org B access Org A run: {resp.status_code} (Expect 404)")

        # 5. Check Org A runs
        resp = await client.get(f"{BASE_URL}/factory/runs", headers=headers_a)
        runs_a = resp.json()
        print(f"Org A runs count: {len(runs_a)}")

        # 6. Hit trial limit for Org A (Limit is 3)
        # Already started 1 run. Start 2 more.
        for i in range(2):
            resp = await client.post(f"{BASE_URL}/factory/start", headers=headers_a, json={
                "requirement": f"Test requirement {i+2} for Org A"
            })
            print(f"Start Run Org A {i+2}: {resp.status_code}")
        
        # Attempt 4th run
        resp = await client.post(f"{BASE_URL}/factory/start", headers=headers_a, json={
            "requirement": "4th run for Org A"
        })
        print(f"Start 4th Run Org A: {resp.status_code} (Expect 402)")
        if resp.status_code == 402:
            print(f"Trial limit reached error: {resp.json()}")

        # 7. Create API Key for Org B
        resp = await client.post(f"{BASE_URL}/auth/api-keys", headers=headers_b, json={
            "name": "My API Key"
        })
        api_key = resp.json()["api_key"]
        print(f"Created API Key for Org B: {api_key[:10]}...")

        # 8. Use API Key to start run for Org B
        headers_api = {"Authorization": f"Bearer {api_key}"}
        resp = await client.post(f"{BASE_URL}/factory/start", headers=headers_api, json={
            "requirement": "API Key run for Org B"
        })
        print(f"Start Run Org B via API Key: {resp.status_code}")

if __name__ == "__main__":
    # Note: Need to have the server running
    asyncio.run(test_multi_tenancy())
