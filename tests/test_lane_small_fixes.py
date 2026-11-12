"""Small backend fixes, each pinned:

1. Manual council review uses the caller's org keys (org_id reaches run_council).
2. Every publisher's events are redacted inside core.pipeline_state.publish_event.
3. No silent `except ...: pass` in the backend lane; the model router logs a broken
   health monitor instead of hiding it.
13. Two identical concurrent client-portal approvals record one decision.

Real code against SQLite (conftest `gw` where a gateway is needed); the council's
model calls and Redis (for #2) are replaced.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import pathlib
import time
import uuid
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

import aether_os.core.db as db
import aether_os.core.model_router as model_router
import aether_os.core.pipeline_state as pipeline_state
from aether_os.core.identity.portal_access import record_approval

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = "S3cr3tPw"
LEAKY = f"could not connect to postgresql://aether:{SECRET}@10.0.0.5/app"


# ── 1 ────────────────────────────────────────────────────────────────────────

def test_manual_council_review_passes_the_callers_org(gw, monkeypatch, tmp_path):
    owner = gw.register("council")
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'completed', 0, 0, 1)", (run_id, owner.org_id))
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / ".aether_os" / "projects" / run_id / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text("def main(): pass\n")
    report = AsyncMock()
    report.return_value.to_dict = lambda: {"ok": True}
    with patch("aether_os.core.council.council_reviewer.run_council", report):
        resp = gw.client.post(f"/factory/runs/{run_id}/council-review", headers=owner.auth)
    assert resp.status_code == 200, resp.text
    assert report.await_args.kwargs["org_id"] == owner.org_id


# ── 2 ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_direct_publishers_are_redacted(monkeypatch, tmp_path):
    # The pipeline_events copy goes to a throwaway database, never a real one.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/ev.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(pipeline_state, "get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline_state, "_local_history", defaultdict(list))

    # What core/llm/providers.py, core/workloop_monitor.py and the phase gates call.
    await pipeline_state.publish_event("run-x", {"type": "llm_error", "error": LEAKY,
                                                 "issues": [LEAKY], "phase": "p01"})
    [stored] = pipeline_state._local_history["run-x"]
    assert SECRET not in stored and json.loads(stored)["phase"] == "p01"


# ── 3 ────────────────────────────────────────────────────────────────────────

_LANE = ("gateway", "core", "orchestrator", "agents")
_OTHER_LANES = ("gateway/routers/prime_", "core/audit/", "core/run_app/", "core/sandbox/")


def _silent_handlers():
    found = []
    for top in _LANE:
        for path in (ROOT / top).rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            if "__pycache__" in rel or rel.startswith(_OTHER_LANES):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.ExceptHandler)
                        and (node.type is None or ast.unparse(node.type) in ("Exception", "BaseException"))
                        and all(isinstance(b, ast.Pass) for b in node.body)):
                    found.append(f"{rel}:{node.lineno}")
    return found


def test_no_silent_broad_except_in_the_backend_lane():
    assert _silent_handlers() == []


def test_router_logs_a_broken_health_monitor(monkeypatch, caplog):
    class Broken:
        def record_success(self, provider):
            raise RuntimeError("ahm store gone")
        record_failure = record_success

    monkeypatch.setattr(model_router, "_get_ahm", lambda: Broken())
    with caplog.at_level(logging.WARNING, logger=model_router.logger.name):
        model_router._ahm_record("anthropic", None)
        model_router._ahm_record("anthropic", "timeout 30s")
    assert sum("health monitor update for anthropic failed" in r.getMessage() for r in caplog.records) == 2


# ── 13 ───────────────────────────────────────────────────────────────────────

def test_identical_concurrent_portal_approvals_record_one_decision(gw):
    owner = gw.register("portalrace")
    project = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'completed', ?, 0, 1)", (project, owner.org_id, time.time()))
    who = {"kind": "portal_token", "id": "tok-race", "label": "Client", "org_id": owner.org_id}

    async def twice(approved, comment):
        return await asyncio.gather(*(record_approval(project, who, approved, comment) for _ in range(2)))

    results = gw.client.portal.call(twice, True, "looks good")
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0]["id"] == results[1][0]["id"]
    # A different decision afterwards is still recorded, and its repeat is not.
    gw.client.portal.call(twice, False, "changed my mind")
    rows = gw.sql("SELECT approved, comment FROM portal_approvals WHERE project_id = ? ORDER BY created_at",
                  (project,))
    assert rows == [(1, "looks good"), (0, "changed my mind")]
    ledgered = gw.sql("SELECT count(*) FROM audit_log WHERE resource_id = ? AND action = 'portal.client_approval'",
                      (project,))[0][0]
    assert ledgered == 2
