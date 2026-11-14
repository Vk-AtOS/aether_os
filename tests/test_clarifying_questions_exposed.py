"""Clarifying questions from the domain model reach the stage metadata and the run-detail payload.

The architecture stage runs for real with its four sub-phases replaced (no model is
called); the domain-IR sub-phase writes a real domain_ir.json through DomainIR.save.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import aether_os.stages.s02_architecture.supervisor as s02
from aether_os.core.domain_ir import DomainIR, IRClarifyingQuestion, IREntity
from aether_os.gateway.routers.factory_run_background import enrich_phases_from_disk
from aether_os.phases.base import TaskResult

pytestmark = pytest.mark.asyncio

QUESTION = IRClarifyingQuestion(
    field_path="Employee.schedule", confidence=0.4,
    question="Is a schedule a weekly pattern or a list of shifts?", options=["weekly", "shifts"])


async def _run_stage(tmp_path, monkeypatch, questions):
    project_dir = tmp_path / "run-1"

    def get_output_dir(_project_id, phase):
        d = project_dir / phase
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=get_output_dir))

    async def sub_phase(self, name, _phase_input, _memory, pm, critical=True):
        out = pm.get_output_dir("run-1", name)
        if name == "p02b_domain_ir":
            ir = DomainIR(domain="general", app_name="Rota")
            ir.entities = [IREntity(name="Employee", table="employees")]
            ir.clarifying_questions = list(questions)
            ir.save(out / "domain_ir.json")
            return TaskResult(output_path=str(out / "domain_ir.json"), confidence=1.0,
                              metadata={"entity_count": 1, "clarifying_questions": len(questions)})
        return TaskResult(output_path="", confidence=1.0)

    monkeypatch.setattr(s02.ArchitectureStageSupervisor, "_run_sub_phase", sub_phase)
    phase_input = SimpleNamespace(project_id="run-1", run_id="run-1", input_data={}, domain="general")
    result = await s02.ArchitectureStageSupervisor().run_task(phase_input, [])
    return result, project_dir


async def test_questions_are_in_stage_metadata_and_run_detail(tmp_path, monkeypatch):
    result, project_dir = await _run_stage(tmp_path, monkeypatch, [QUESTION])

    # Stage metadata is merged into the run context (and so into the checkpoint).
    assert result.success and result.metadata["has_questions"] is True
    assert result.metadata["clarifying_questions"] == [{
        "field_path": "Employee.schedule", "confidence": 0.4,
        "question": "Is a schedule a weekly pattern or a list of shifts?",
        "options": ["weekly", "shifts"]}]

    # What GET /factory/runs/{id} returns for the stage row the pipeline actually writes.
    phases = enrich_phases_from_disk({"s02_architecture": {"status": "passed"}}, project_dir, str(project_dir) + "/")
    assert phases["s02_architecture"]["output_file"] == "s02_architecture/s02_architecture.json"
    assert phases["s02_architecture"]["output"]["clarifying_questions"] == result.metadata["clarifying_questions"]
    assert "p02b_domain_ir" not in phases   # the key the panel reads today never exists


async def test_no_questions_is_an_empty_list_not_a_missing_key(tmp_path, monkeypatch):
    result, project_dir = await _run_stage(tmp_path, monkeypatch, [])
    assert result.metadata["clarifying_questions"] == [] and result.metadata["has_questions"] is False
    saved = json.loads((project_dir / "s02_architecture" / "s02_architecture.json").read_text())
    assert saved["clarifying_questions"] == [] and saved["has_questions"] is False
