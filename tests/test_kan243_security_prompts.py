"""KAN-243: every model code-writing prompt in p04* carries the security rules of the run's stack (from the spec), and the
files a model writes are recorded so the s11 rule-pack gate repairs them instead of blaming the templates."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aether_os.core.llm import client as llm_client
from aether_os.core.rulepacks.provenance import load_model_files
from aether_os.core.rulepacks.spec_rules import security_rules_for, spec_features


class Recorder:
    def __init__(self, answer=""):
        self.prompts, self.answer = [], answer

    async def call(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.answer


@pytest.fixture
def model(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: rec)
    monkeypatch.setenv("ENVIRONMENT", "production")
    return rec


def _assert_rules(prompt: str, design: bool = False):
    assert "SECURITY RULES" in prompt and "[SEC-001, SEC-021]" in prompt
    assert "DESIGN RULES" not in prompt or design


def test_spec_features_follow_the_spec():
    assert spec_features({}) == ["fastapi", "sqlalchemy", "jwt-auth", "react", "docker"]
    ctx = {"raw_input": "an AI agent that reads uploaded invoices",
           "entities": [{"name": "Doc", "fields": [{"name": "scan", "type": "file"}]}]}
    assert {"file-upload", "llm-agent"} <= set(spec_features(ctx))
    backend = security_rules_for(ctx, "backend")
    assert "[SEC-007]" in backend and "dangerouslySetInnerHTML" not in backend
    assert "dangerouslySetInnerHTML" in security_rules_for(ctx, "frontend")


def test_p04b_prompts_carry_the_backend_security_rules(model, tmp_path):
    from aether_os.phases.p04b_business_logic import task_agent
    ir = tmp_path / "domain_ir.json"
    ir.write_text(json.dumps({"domain": "crm", "entities": [{"name": "Lead", "table": "leads", "fields": []}]}))
    data = {"project_name": "X", "domain": "crm", "domain_ir_path": str(ir), "raw_input": "leads"}
    asyncio.run(task_agent.run(SimpleNamespace(input_data=data, project_id="p"), [], tmp_path / "out"))
    assert len(model.prompts) >= 2
    for p in model.prompts[:2]:
        _assert_rules(p, design=False)
        assert "[SEC-008]" in p


def test_p04c_prompt_carries_the_rules_and_the_client_is_recorded_as_model_written(model, tmp_path):
    from aether_os.phases.p04c_integration_codegen import task_agent
    app = tmp_path / "p04a_backend_codegen"
    (app / "src").mkdir(parents=True)
    (app / "src" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    model.answer = "import httpx\n\n\nclass WeatherlyClient:\n    \"\"\"" + "x" * 220 + "\"\"\"\n"
    data = {"project_dir": str(tmp_path), "integration_map": {"integrations": [{"name": "Weatherly", "type": "api"}]}}
    asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "p04c"))
    _assert_rules(model.prompts[0], design=False)
    assert load_model_files(app) == {"src/services/weatherly_client.py"}


def test_seed_and_startup_fix_prompts_carry_the_rules(model, tmp_path, monkeypatch):
    from aether_os.phases.p04_backend import task_agent as p04
    monkeypatch.setattr(p04, "get_llm_client", lambda: model)
    from aether_os.phases.p04a_backend_codegen.crud_generator_seed import generate_llm_seed
    asyncio.run(generate_llm_seed("X", [{"name": "Lead", "fields": []}], "crm"))
    _assert_rules(model.prompts[-1], design=False)
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    main = app / "src" / "main.py"
    main.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    model.answer = "from fastapi import FastAPI\n\napp = FastAPI()\n# fixed: the imports now resolve for the generated application, nothing else changed\n"
    asyncio.run(p04._smoke_repair(main, "NameError: x", 1))
    _assert_rules(model.prompts[-1], design=False)
    assert load_model_files(app) == {"src/main.py"}


def test_provenance_ledger_is_never_exported(tmp_path):
    from aether_os.core.project_export import SKIP_DIRS
    from aether_os.core.rulepacks.provenance import LEDGER
    assert Path(LEDGER).parts[0] in SKIP_DIRS
