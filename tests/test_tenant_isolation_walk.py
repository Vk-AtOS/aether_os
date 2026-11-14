"""KAN-115: walk the whole route table; an org-A user must not reach an org-B object by id.

For every route with a path parameter we substitute org B's real object ids (run, webhook,
workspace, api key, user) and call it as org A's *admin/owner* (the strongest non-platform
role). Any 2xx or 5xx is a leak (or a crash). 4xx means refused / not found / body invalid.
"""
import asyncio
import re
import time
import uuid

import pytest

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run

# Routes whose path parameter is not an org-owned object, or that are public by design.
SKIP_PREFIXES = ("/dashboard", "/app-preview", "/auth/saml", "/auth/oauth", "/scim", "/portal",
                 "/client-portal", "/mcp", "/system/feature-flags", "/intelligence/global-patterns",
                 "/admin/error-registry", "/guardian", "/settings/phases", "/agents", "/velaris",
                 "/chat", "/prime", "/auth/verify", "/auth/reset", "/auth/invite", "/webhooks/cicd")


def _seed_b(gw, b):
    run_id = str(uuid.uuid4())

    async def add_run():
        async with get_session_factory()() as s:
            s.add(Run(id=run_id, org_id=b.org_id, command="b-secret", status="completed",
                      started_at=time.time(), project_name="b-project", user_id=b.user_id))
            await s.commit()
    asyncio.run(add_run())
    ids = {"run_id": run_id, "rid": run_id, "user_id": b.user_id}
    r = gw.client.post("/auth/api-keys", headers=b.auth, json={"name": "bk"})
    if r.status_code in (200, 201):
        ids["key_id"] = r.json().get("id") or r.json().get("key_id")
    r = gw.client.post("/webhooks", headers=b.auth, json={"url": "https://example.com/h", "events": []})
    if r.status_code in (200, 201):
        ids["webhook_id"] = r.json().get("id")
    r = gw.client.post("/workspaces", headers=b.auth, json={"name": "bw"})
    if r.status_code in (200, 201):
        ids["workspace_id"] = r.json().get("id")
    return ids


def _routes(app):
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        params = re.findall(r"{(\w+)(?::\w+)?}", path)
        if not params or path.startswith(SKIP_PREFIXES):
            continue
        for m in sorted(r.methods or []):
            if m not in ("HEAD", "OPTIONS"):
                out.append((m, path, params))
    # reads first so a leaking DELETE cannot hide later findings
    return sorted(out, key=lambda x: x[0] != "GET")


def test_org_a_cannot_reach_org_b_objects_by_id(gw):
    a, b = gw.register("tenanta"), gw.register("tenantb")
    ids = _seed_b(gw, b)
    # control: the owner of the seeded run really can read it, so a 404 for A means isolation
    assert gw.client.get(f"/factory/runs/{ids['run_id']}", headers=b.auth).status_code == 200
    leaks, checked = [], 0
    for method, path, params in _routes(gw.app):
        if not any(p in ids and ids[p] for p in params):
            continue
        url = re.sub(r"{(\w+)(?::\w+)?}", lambda m: str(ids.get(m.group(1)) or "x"), path)
        resp = gw.client.request(method, url, headers=a.auth,
                                 json={} if method in ("POST", "PUT", "PATCH") else None)
        checked += 1
        # 503 = optional Velaris backend not running here (nothing to prove against)
        if resp.status_code < 300 or (resp.status_code >= 500 and resp.status_code != 503):
            leaks.append(f"{method} {path} -> {resp.status_code} {resp.text[:120]}")
    assert checked > 40, f"walker only exercised {checked} routes"
    assert not leaks, "cross-tenant exposure:\n" + "\n".join(leaks)
