"""KAN-247: a run is stored as "completed" only when every required stage passed.

All 11 "completed" production runs of the 28 Nov audit had all_stages_ok=false; the DeliveryCouncil alone
decided the final status, and a council that did not run wrote "completed".
"""
import asyncio

from aether_os.orchestrator.stage_gate import final_run_status, release_blockers, summarize_stage_outcomes


# ── run-level: "completed" only when every required stage passed ────────────

def _passed(meta=None):
    return {"status": "passed", "metadata": meta or {}}


def _clean_run():
    return {
        "s03_backend": _passed(),
        "s04_frontend": _passed({"build_ok": True, "tsc_errors": 0}),
        "s06_testing": _passed({"gate": {"passed": True, "tests_failed_but_did_not_block": False}}),
        "s07_healing": _passed({"healing_passed": True, "not_verified": []}),
        "s09_devops": _passed({"not_verified": []}),
        "s11_handoff": _passed({"not_verified": []}),
    }


def test_clean_run_is_completed():
    assert release_blockers(_clean_run()) == []
    assert final_run_status(_clean_run(), True) == ("completed", None)
    assert final_run_status(_clean_run(), None) == ("completed", None)       # council unavailable: advisory
    assert final_run_status(_clean_run(), False)[0] == "needs_review"
    assert summarize_stage_outcomes(_clean_run())["all_stages_ok"] is True


def test_deferred_tests_not_run_keep_the_run_from_completed():
    run = _clean_run()
    run["s07_healing"]["metadata"]["not_verified"] = ["e2e_testing: not run: playwright missing"]
    status, msg = final_run_status(run, True)
    assert status == "needs_review" and "e2e_testing: not run" in msg
    assert summarize_stage_outcomes(run)["all_stages_ok"] is False


def test_app_not_verified_or_stage_failed_is_needs_review():
    run = _clean_run()
    run["s07_healing"]["metadata"]["healing_passed"] = False
    assert "not verified running" in release_blockers(run)[0]
    run = _clean_run()
    run["s09_devops"] = {"status": "timeout", "error": "phase timed out"}
    assert release_blockers(run) == ["s09_devops timeout: phase timed out"]


def test_frontend_must_build_and_type_check():
    run = _clean_run()
    run["s04_frontend"]["metadata"] = {"build_ok": True, "tsc_errors": 4, "tsc_messages": ["CrudModal.tsx TS2345"]}
    assert "4 TypeScript error(s): CrudModal.tsx TS2345" in release_blockers(run)[0]
    run["s04_frontend"]["metadata"] = {}
    assert "not recorded" in release_blockers(run)[0]
    run["s04_frontend"] = {"status": "skipped", "metadata": {"skipped_reason": "no_frontend_selected"}}
    assert release_blockers(run) == []                                        # no UI was requested


def test_failing_unit_tests_need_healing():
    run = _clean_run()
    run["s06_testing"] = {"status": "failed", "metadata": {"gate": {
        "passed": True, "tests_failed_but_did_not_block": True, "tests_failed": 4}}}
    assert release_blockers(run) == []                                        # s07 healed them
    run["s07_healing"]["metadata"]["healing_passed"] = False
    assert any("4 unit test(s) failed and were not healed" in b for b in release_blockers(run))


# ── the stored run status (DeliveryCouncil passing is not enough) ────────────

def _stored_status(tmp_path, monkeypatch, results, council):
    import time

    from sqlalchemy import select

    import aether_os.core.db as db
    from aether_os.core.models import Run
    from aether_os.orchestrator import artifact_collector as ac

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/s.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    events = []

    async def fake_publish(rid, ev):
        events.append(ev)
    monkeypatch.setattr(ac, "publish_event", fake_publish)
    monkeypatch.setattr(ac, "DeliveryCouncil", lambda: council)

    async def go():
        async with db.get_engine().begin() as conn:
            await conn.run_sync(db.Base.metadata.create_all)
        async with db.get_session_factory()() as s:
            s.add(Run(id="r1", status="council_review", started_at=time.time()))
            await s.commit()
        await ac.delivery_council_check("r1", "p", "raw", "general", results, None, {})
        async with db.get_session_factory()() as s:
            run = (await s.execute(select(Run).where(Run.id == "r1"))).scalar_one()
        await db.get_engine().dispose()
        return run.status, run.message, events
    return asyncio.run(go())


class _PassingCouncil:
    async def run(self, **kw):
        return {"passed": True, "score": 0.9, "reason": "ok", "suggestions": []}


class _UnavailableCouncil:
    async def run(self, **kw):
        raise asyncio.TimeoutError


def test_council_pass_with_an_unstarted_app_is_stored_as_needs_review(tmp_path, monkeypatch):
    run = _clean_run()
    run["s07_healing"]["metadata"]["not_verified"] = ["performance_testing: not run: app did not start"]
    status, message, events = _stored_status(tmp_path, monkeypatch, run, _PassingCouncil())
    assert status == "needs_review" and "performance_testing: not run" in message
    assert events[-1]["status"] == "needs_review"


def test_clean_run_with_passing_council_is_completed(tmp_path, monkeypatch):
    status, message, _ = _stored_status(tmp_path, monkeypatch, _clean_run(), _PassingCouncil())
    assert (status, message) == ("completed", None)


def test_unavailable_council_no_longer_forces_completed(tmp_path, monkeypatch):
    run = _clean_run()
    run["s09_devops"]["metadata"]["not_verified"] = ["deploy: not run: Docker not available"]
    status, message, _ = _stored_status(tmp_path, monkeypatch, run, _UnavailableCouncil())
    assert status == "needs_review" and "Docker not available" in message and "did not run" in message
