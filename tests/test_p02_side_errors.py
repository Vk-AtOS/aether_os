"""Run e53e5f12 side errors (KAN-258): each had a root cause in the platform, not in the run."""
from __future__ import annotations

import asyncio
import json

from aether_os.orchestrator.phase_hooks import _hook_p02_architecture
from aether_os.phases.p02_architecture import task_agent
from aether_os.phases.p02b_domain_ir.validator import validate_domain_ir


def test_architecture_cache_is_written_even_when_the_cache_directory_does_not_exist(tmp_path):
    # ~/.aether_os/spec_cache is created lazily by another module; a fresh host raised "No such file ... <run>.json"
    # from write_text and failed p02 for a cache. A cache that cannot be written is a warning, never a failure.
    target = tmp_path / "missing" / "dir" / "run.json"
    task_agent._write_cache(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    blocker = tmp_path / "file"
    blocker.write_text("x")
    task_agent._write_cache(blocker / "run.json", {"a": 1})      # parent is a file: OSError is swallowed and logged
    task_agent._write_cache(None, {"a": 1})


def test_stage_output_directory_is_resolved_to_its_architecture_json(tmp_path):
    # s02's output_path is the stage directory; read_text on it raised "Is a directory".
    stage = tmp_path / "s02_architecture"
    stage.mkdir()
    (stage / "architecture.json").write_text(json.dumps({"tech_stack": {"backend": "fastapi"}}))
    ctx: dict = {}
    asyncio.run(_hook_p02_architecture("s02_architecture", {"output_path": str(stage)}, tmp_path, ctx))
    assert ctx["architecture_json"]["tech_stack"]["backend"] == "fastapi"
    assert ctx["p02_architecture_path"] == str(stage / "architecture.json")


def test_a_spec_without_a_user_entity_gets_no_missing_user_warning():
    # The generated app always has its own users table, login and register; the D5 warning claimed registration
    # "may fail at runtime" for every spec that did not name a User entity.
    ir = {"entities": [
        {"name": "Appointment", "table": "appointments", "fields": [{"name": "patient", "type": "string"}]},
        {"name": "Doctor", "table": "doctors", "fields": [{"name": "name", "type": "string"}]}]}
    report = validate_domain_ir(ir)
    assert not any("D5" in w for w in report.warnings)
