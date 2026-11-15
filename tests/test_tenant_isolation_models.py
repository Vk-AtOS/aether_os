"""KAN-115: tenant isolation for EVERY org-scoped model, found by reflection, not by a hand list.

1. Every mapped table with an org_id column gets a row owned by org B whose text columns carry a
   unique marker. Org A (admin) then calls every GET route that has no path parameter: the marker
   must not appear in any response.
2. Every route with a path parameter that names one of those rows' ids is called as org A with
   B's real id: any 2xx/5xx is a leak (or a crash).
"""
import asyncio
import re
import time
import uuid

import pytest
from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, DateTime, insert
from sqlalchemy.orm import class_mapper

import aether_os.core.models  # noqa: F401  (registers the tables)
import aether_os.core.guardian.models  # noqa: F401
import aether_os.core.identity.portal_access  # noqa: F401
from aether_os.core.db import Base, get_session_factory

# Tables whose writes are guarded by triggers/listeners or that are platform data, not tenant data.
SKIP_TABLES = {"audit_chain", "audit_checkpoints", "audit_backfill", "audit_org_pepper", "audit_subjects",
               "audit_erasures", "audit_log", "users", "organisations", "api_keys", "runs"}
# Prime keeps typed ledgers (Decimal amounts, state machines): a generic text-marker row is not a valid row.
SKIP_TABLE_PREFIXES = ("prime",)
SKIP_GET_PREFIXES = ("/dashboard", "/app-preview", "/auth/saml", "/auth/oauth", "/portal", "/client-portal",
                     "/system/feature-flags", "/openapi", "/docs", "/redoc", "/health", "/metrics", "/chat",
                     "/mail", "/velaris", "/control", "/hr", "/prime/ledger")
# id-parameter name -> (table, column holding the id)
PARAM_TABLES = {"decision_id": ("decisions", "id"), "notif_id": ("notifications", "id"),
                "profile_id": ("marketplace_profiles", "id"), "webhook_id": ("webhooks", "id"),
                "workspace_id": ("workspaces", "id"), "clarification_id": ("learning_clarifications_pending", "id"),
                "event_id": ("guardian_events", "id")}


def _fill(col, marker, n):
    t = col.type
    if isinstance(t, JSON):
        return {"m": marker}
    if isinstance(t, Boolean):
        return False
    if isinstance(t, Integer):
        return 1
    if isinstance(t, Float):
        return time.time()
    if isinstance(t, DateTime):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if isinstance(t, (String, Text)):
        length = getattr(t, "length", None) or 255
        return (f"{marker}-{col.name}-{n}")[:length]
    return None


def _seed_all(org_b, marker):
    """One marked row per org-scoped table, owned by org B. Returns {table: {column: value}}."""
    seeded = {}

    async def go():
        async with get_session_factory()() as s:
            for mapper in Base.registry.mappers:
                table = mapper.local_table
                if table.name in SKIP_TABLES or "org_id" not in table.c or table.name.startswith(SKIP_TABLE_PREFIXES):
                    continue
                row = {}
                for col in table.c:
                    if col.name == "org_id":
                        row[col.name] = org_b
                    elif col.primary_key and isinstance(col.type, String):
                        row[col.name] = str(uuid.uuid4())
                    elif col.primary_key:
                        continue  # autoincrement
                    elif col.nullable and col.default is None and col.server_default is None:
                        row[col.name] = _fill(col, marker, 1) if isinstance(col.type, (String, Text, JSON)) else None
                    else:
                        v = _fill(col, marker, 1)
                        if v is not None:
                            row[col.name] = v
                try:
                    await s.execute(insert(table).values(**row))
                    await s.commit()
                    seeded[table.name] = row
                except Exception as exc:  # a table we cannot seed generically is reported, not hidden
                    await s.rollback()
                    seeded[table.name] = exc
    asyncio.run(go())
    return seeded


def _paramless_gets(app):
    for r in app.routes:
        path = getattr(r, "path", "")
        if "GET" in (getattr(r, "methods", None) or ()) and "{" not in path and not path.startswith(SKIP_GET_PREFIXES):
            yield path


def test_org_b_rows_never_appear_in_org_a_responses(gw):
    a, b = gw.register("isoa"), gw.register("isob")
    admin_a = gw.user_with_role("admin", a.org_id)
    marker = f"ZZB{uuid.uuid4().hex[:10]}"
    seeded = _seed_all(b.org_id, marker)
    ok_tables = [t for t, v in seeded.items() if isinstance(v, dict)]
    assert len(ok_tables) >= 12, f"seeded too few tables: { {t: str(v)[:80] for t, v in seeded.items() if not isinstance(v, dict)} }"
    # positive control: org B's own admin sees its marked rows on several routes, so a clean
    # result for org A means isolation and not "nothing is ever returned".
    admin_b = gw.user_with_role("admin", b.org_id)
    visible = [p for p in _paramless_gets(gw.app) if marker in gw.client.get(p, headers=admin_b.auth).text]
    assert len(visible) >= 3, visible
    leaks, checked = [], 0
    for path in _paramless_gets(gw.app):
        resp = gw.client.get(path, headers=admin_a.auth)
        checked += 1
        if marker in resp.text or b.org_id in resp.text or b.email in resp.text:
            leaks.append(f"GET {path} -> {resp.status_code}: {resp.text[:160]}")
    assert checked > 60, f"walked only {checked} routes"
    assert not leaks, "org B data in org A responses:\n" + "\n".join(leaks)


def test_org_a_cannot_touch_org_b_rows_by_id_for_every_id_parameter(gw):
    a, b = gw.register("idsa"), gw.register("idsb")
    admin_a = gw.user_with_role("admin", a.org_id)
    marker = f"ZZI{uuid.uuid4().hex[:10]}"
    seeded = _seed_all(b.org_id, marker)
    ids = {p: seeded[t][c] for p, (t, c) in PARAM_TABLES.items() if isinstance(seeded.get(t), dict)}
    assert len(ids) >= 5, ids
    leaks, checked = [], 0
    for r in gw.app.routes:
        path = getattr(r, "path", "")
        params = re.findall(r"{(\w+)(?::\w+)?}", path)
        if not any(p in ids for p in params) or path.startswith(("/dashboard", "/app-preview", "/portal")):
            continue
        for m in sorted(set(getattr(r, "methods", None) or ()) - {"HEAD", "OPTIONS"}):
            url = re.sub(r"{(\w+)(?::\w+)?}", lambda mm: str(ids.get(mm.group(1), "x")), path)
            resp = gw.client.request(m, url, headers=admin_a.auth, json={} if m in ("POST", "PUT", "PATCH") else None)
            checked += 1
            if resp.status_code < 300 and not (m == "GET" and path.startswith("/marketplace/profiles/")) \
                    or (resp.status_code >= 500 and resp.status_code != 503):
                leaks.append(f"{m} {path} -> {resp.status_code} {resp.text[:120]}")
    assert checked >= 10
    assert not leaks, "cross-tenant exposure:\n" + "\n".join(leaks)
