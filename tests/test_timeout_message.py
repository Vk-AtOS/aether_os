"""A run that times out says why on Run.message, so the UI never has to fall back to events."""
from __future__ import annotations

import asyncio
import time
import uuid


from aether_os.orchestrator.factory_pipeline import FactoryPipeline
from aether_os.orchestrator.stage_gate import record_run_timeout, timeout_reason


def _run(gw, org_id, phase="s03_backend"):
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version, current_phase) "
           "VALUES (?, ?, 'factory: x', 'x', 'running', ?, 0, 1, ?)", (run_id, org_id, time.time(), phase))
    return run_id


def _row(gw, run_id):
    return gw.sql("SELECT status, message FROM runs WHERE id = ?", (run_id,))[0]


def test_reasons_are_never_empty_and_redacted():
    assert "s03_backend" in timeout_reason(120, "s03_backend") and "120 seconds" in timeout_reason(120, "s03_backend")
    assert "30 minutes" in timeout_reason(1800)
    leaked = timeout_reason(60, "s03_backend sk-ant-api03-" + "a" * 40)
    assert "sk-ant-api03-" + "a" * 40 not in leaked


def test_whole_build_timeout_stores_a_reason_naming_the_stage(gw):
    owner = gw.register("tmo")
    run_id = _run(gw, owner.org_id)

    async def go():
        from aether_os.core.audit.ledger import get_ledger
        return await record_run_timeout(get_ledger(), run_id, 1800)

    reason = gw.client.portal.call(go)
    status, message = _row(gw, run_id)
    assert status == "timeout" and message == reason
    assert "30 minutes" in message and "s03_backend" in message


def test_pipeline_timeout_path_writes_the_message(gw, monkeypatch):
    owner = gw.register("tmo2")
    run_id = _run(gw, owner.org_id, "s02_architecture")
    monkeypatch.setenv("PIPELINE_TIMEOUT_MINUTES", "0.0005")   # 30 ms

    async def hang(self, *a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(FactoryPipeline, "_execute_pipeline", hang)

    async def go():
        return await FactoryPipeline().run(client_id="c", raw_input="x", run_id=run_id, org_id=owner.org_id)

    result = gw.client.portal.call(go)
    status, message = _row(gw, run_id)
    assert result["status"] == "timeout" and result["error"] == message
    assert status == "timeout" and message and "s02_architecture" in message


def test_critical_stage_timeout_path_writes_the_message(gw):
    owner = gw.register("tmo3")
    run_id = _run(gw, owner.org_id)

    async def go():
        return await FactoryPipeline()._abort_run(run_id, timeout_reason(300, "s03_backend"), failed_stage="s03_backend")

    out = gw.client.portal.call(go)
    status, message = _row(gw, run_id)
    assert status == "failed" and "did not finish within 300 seconds" in message and out["error"] == message
