"""Clarifying answers: org-checked, validated against the stored questions, size-limited,
ledgered, stored for s02, and applied to the domain model; the run restarts from s02."""
from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import aether_os.core.projects as projects_mod
from aether_os.core.domain_ir import DomainIR, IRClarifyingQuestion, IREntity, IRField
from aether_os.orchestrator import clarifying

QUESTIONS = [
    {"field_path": "Employee.schedule", "confidence": 0.4, "question": "Weekly or shifts?",
     "options": ["weekly", "shifts"]},
    {"field_path": "Employee.notes", "confidence": 0.3, "question": "What is notes?", "options": []},
]


@pytest.fixture(scope="module")
def projects_root(tmp_path_factory):
    saved = projects_mod._manager
    root = tmp_path_factory.mktemp("projects")
    projects_mod._manager = projects_mod.ProjectManager(root=root)
    yield root
    projects_mod._manager = saved


def _run(gw, projects_root, org_id, status="completed", checkpoint=None, questions=QUESTIONS):
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version, checkpoint_data) "
           "VALUES (?, ?, 'factory: rota', 'a rota app', ?, ?, 0, 1, ?)",
           (run_id, org_id, status, time.time(), json.dumps(checkpoint) if checkpoint else None))
    out = projects_root / run_id / "s02_architecture"
    out.mkdir(parents=True)
    (out / "s02_architecture.json").write_text(json.dumps({"clarifying_questions": questions}))
    return run_id


def _post(gw, who, run_id, body):
    return gw.client.post(f"/factory/runs/{run_id}/clarifying-answers", headers=who.auth, json=body)


def test_answers_are_recorded_returned_and_ledgered(gw, projects_root):
    owner = gw.register("clar")
    run_id = _run(gw, projects_root, owner.org_id)
    resp = _post(gw, owner, run_id, {"answers": {"Employee.schedule": "weekly", "Employee.notes": "free text"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["recorded"] == ["Employee.notes", "Employee.schedule"] and resp.json()["restarted"] is False

    got = gw.client.get(f"/factory/runs/{run_id}/clarifying-answers", headers=owner.auth).json()
    assert got["answers"] == {"Employee.schedule": "weekly", "Employee.notes": "free text"}
    assert [q["field_path"] for q in got["questions"]] == ["Employee.schedule", "Employee.notes"]
    assert clarifying.load_answers(run_id)["Employee.schedule"] == "weekly"

    rows = gw.sql("SELECT log_metadata FROM audit_log WHERE action = 'run.clarifying_answers' AND resource_id = ?", (run_id,))
    assert rows, "the answers were not ledgered"
    meta = json.loads(rows[0][0])
    assert meta["fields"] == ["Employee.notes", "Employee.schedule"] and "free text" not in rows[0][0]


def test_another_orgs_run_is_a_404(gw, projects_root):
    a, b = gw.register("clara"), gw.register("clarb")
    run_id = _run(gw, projects_root, a.org_id)
    assert _post(gw, b, run_id, {"answers": {"Employee.notes": "x"}}).status_code == 404
    assert gw.client.get(f"/factory/runs/{run_id}/clarifying-answers", headers=b.auth).status_code == 404
    assert clarifying.load_answers(run_id) == {}


@pytest.mark.parametrize("answers", [
    {"Employee.salary": "x"},                       # not a stored question
    {"Employee.schedule": "monthly"},               # outside the question's options
    {"Employee.notes": "   "},                      # empty
    {"Employee.notes": "x" * (clarifying.MAX_VALUE_CHARS + 1)},   # oversized
    {"Employee.notes": {"nested": 1}},              # not text
    {},                                             # nothing
])
def test_invalid_answers_are_422_and_record_nothing(gw, projects_root, answers):
    owner = gw.register("clarv")
    run_id = _run(gw, projects_root, owner.org_id)
    assert _post(gw, owner, run_id, {"answers": answers}).status_code == 422
    assert clarifying.load_answers(run_id) == {}


def test_too_many_answers_are_refused(gw, projects_root):
    owner = gw.register("clarmany")
    run_id = _run(gw, projects_root, owner.org_id)
    many = {f"Employee.f{i}": "x" for i in range(clarifying.MAX_ANSWERS + 1)}
    assert _post(gw, owner, run_id, {"answers": many}).status_code == 422


def test_a_run_without_questions_is_409(gw, projects_root):
    owner = gw.register("clarnone")
    run_id = _run(gw, projects_root, owner.org_id, questions=[])
    assert _post(gw, owner, run_id, {"answers": {"Employee.notes": "x"}}).status_code == 409


def test_restart_resumes_at_s02_with_the_answers_in_place(gw, projects_root):
    owner = gw.register("clarr")
    ckpt = {"last_completed_phase": "s05_quality", "accumulated_context": {"raw_input": "a rota app", "spec_review": {"ok": 1}}}
    run_id = _run(gw, projects_root, owner.org_id, status="failed", checkpoint=ckpt)
    started = []

    class FakeFactory:
        async def run(self, **kw):
            started.append((kw, clarifying.load_answers(kw["run_id"])))

    with patch("aether_os.gateway.services.run_start.get_factory", return_value=FakeFactory()):
        resp = _post(gw, owner, run_id, {"answers": {"Employee.notes": "free text"}, "restart": True})
        import asyncio
        gw.client.portal.call(asyncio.sleep, 0.2)
    assert resp.status_code == 200 and resp.json()["restart_from"] == "s02_architecture"
    assert started and started[0][0]["run_id"] == run_id and started[0][1] == {"Employee.notes": "free text"}
    stored = json.loads(gw.sql("SELECT checkpoint_data FROM runs WHERE id = ?", (run_id,))[0][0])
    assert stored["last_completed_phase"] == "s01_intake" and stored["accumulated_context"]["raw_input"] == "a rota app"


def test_restart_is_refused_while_running_or_without_a_checkpoint_and_records_nothing(gw, projects_root):
    owner = gw.register("clarbusy")
    busy = _run(gw, projects_root, owner.org_id, status="running",
                checkpoint={"last_completed_phase": "s01_intake", "accumulated_context": {"a": 1}})
    nockpt = _run(gw, projects_root, owner.org_id, status="failed")
    for run_id in (busy, nockpt):
        assert _post(gw, owner, run_id, {"answers": {"Employee.notes": "x"}, "restart": True}).status_code == 409
        assert clarifying.load_answers(run_id) == {}


def test_two_restarts_that_both_passed_the_busy_check_start_exactly_one_build(gw, projects_root):
    """Both requests read the run as 'failed' (the stale read of a real race); the single
    conditional UPDATE lets only the first one claim it and start a build."""
    import asyncio
    from aether_os.gateway.routers import clarifying_router
    owner = gw.register("clarrace")
    ckpt = {"last_completed_phase": "s05_quality", "accumulated_context": {"raw_input": "x"}}
    run_id = _run(gw, projects_root, owner.org_id, status="failed", checkpoint=ckpt)
    stale = SimpleNamespace(id=run_id, org_id=owner.org_id, status="failed", checkpoint_data=ckpt,
                            raw_input="a rota app", command=None)

    async def stale_read(_run_id, _org):
        return stale
    started = []

    class FakeFactory:
        async def run(self, **kw):
            started.append(kw["run_id"])

    with patch.object(clarifying_router, "_run_or_404", stale_read), \
            patch("aether_os.gateway.services.run_start.get_factory", return_value=FakeFactory()):
        codes = [_post(gw, owner, run_id, {"answers": {"Employee.notes": "x"}, "restart": True}).status_code
                 for _ in range(2)]
        gw.client.portal.call(asyncio.sleep, 0.2)
    assert sorted(codes) == [200, 409] and started == [run_id]
    assert gw.sql("SELECT status FROM runs WHERE id = ?", (run_id,))[0][0] == "running"


# ── feeding the answers into the domain model ──────────────────────────────────

def _ir():
    ir = DomainIR(domain="general", app_name="Rota")
    ir.entities = [IREntity(name="Employee", table="employees",
                            fields=[IRField(name="schedule", type="string", confidence=0.4)])]
    ir.clarifying_questions = [IRClarifyingQuestion(field_path="Employee.schedule", confidence=0.4,
                                                    question="q", options=["weekly", "shifts"])]
    return ir


def test_applying_answers_closes_the_question_and_survives_save_and_load(tmp_path):
    ir = _ir()
    assert clarifying.apply_to_ir(ir, {"Employee.schedule": "weekly"}) == ["Employee.schedule"]
    assert ir.clarifying_questions == [] and ir.entities[0].fields[0].confidence == 1.0
    ir.save(tmp_path / "ir.json")
    assert DomainIR.load(tmp_path / "ir.json").clarifications == {"Employee.schedule": "weekly"}


def test_requirement_text_carries_the_answers():
    text = clarifying.requirement_suffix({"Employee.schedule": "weekly"})
    assert "Employee.schedule: weekly" in text and "authoritative" in text
    assert clarifying.requirement_suffix({}) == ""


@pytest.mark.asyncio
async def test_s02_puts_recorded_answers_in_the_context_and_summary(tmp_path, monkeypatch):
    import aether_os.stages.s02_architecture.supervisor as s02
    from aether_os.phases.base import TaskResult
    run_id = "run-clar"
    monkeypatch.setattr(clarifying, "load_answers", lambda rid: {"Employee.schedule": "weekly"})
    monkeypatch.setattr(s02, "load_answers", clarifying.load_answers)
    project_dir = tmp_path / run_id
    seen = {}

    def get_output_dir(_pid, phase):
        d = project_dir / phase
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=get_output_dir))

    async def sub_phase(self, name, phase_input, _memory, pm):
        out = pm.get_output_dir(run_id, name)
        if name == "p02b_domain_ir":
            seen["answers_at_p02b"] = dict(phase_input.input_data["clarifying_answers"])
            ir = _ir()
            ir.clarifying_questions = []
            ir.save(out / "domain_ir.json")
            return TaskResult(output_path=str(out / "domain_ir.json"), confidence=1.0, metadata={})
        return TaskResult(output_path="", confidence=1.0)

    monkeypatch.setattr(s02.ArchitectureStageSupervisor, "_run_sub_phase", sub_phase)
    pi = SimpleNamespace(project_id=run_id, run_id=run_id, input_data={}, domain="general")
    result = await s02.ArchitectureStageSupervisor().run_task(pi, [])
    assert seen["answers_at_p02b"] == {"Employee.schedule": "weekly"}
    assert result.metadata["clarifying_answers"] == {"Employee.schedule": "weekly"}
    summary = json.loads((project_dir / "s02_architecture" / "s02_architecture.json").read_text())
    assert summary["clarifying_answers"] == {"Employee.schedule": "weekly"} and summary["has_questions"] is False
