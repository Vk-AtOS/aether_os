"""KAN-110: erasing or exporting one user must not touch the rest of the organisation."""
import time
import uuid
import asyncio

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run


def _run(org_id, user_id, name):
    async def go():
        async with get_session_factory()() as s:
            s.add(Run(id=str(uuid.uuid4()), org_id=org_id, user_id=user_id, project_name=name,
                      status="completed", started_at=time.time()))
            await s.commit()
    asyncio.run(go())


def test_export_contains_only_the_users_own_runs(gw):
    owner = gw.register("exportorg")
    other = gw.user_with_role("member", owner.org_id)
    _run(owner.org_id, owner.user_id, "owner-run")
    _run(owner.org_id, other.user_id, "other-run")
    r = gw.client.get("/account/data-export", headers=other.auth)
    assert r.status_code == 200, r.text
    assert {x["project_name"] for x in r.json()["runs"]} == {"other-run"}


def test_erasing_one_member_keeps_the_orgs_api_keys(gw):
    owner = gw.register("eraseorg")
    key = gw.client.post("/auth/api-keys", headers=owner.auth, json={"name": "ci"})
    assert key.status_code in (200, 201), key.text
    member = gw.user_with_role("member", owner.org_id)
    assert gw.client.delete("/account", headers=member.auth).status_code == 200
    active = gw.sql("SELECT is_active FROM api_keys WHERE org_id=?", (owner.org_id,))
    assert active and all(row[0] for row in active)
