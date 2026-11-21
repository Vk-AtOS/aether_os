"""Regression: p00 used to put the profile NAME (a str) in TaskResult.metadata["build_profile"].

The s01 supervisor merges that metadata into the shared context, so p00c (and every later
reader) got a str and crashed on build_profile.get(...): run 09297aa3 logged
"s01 sub-phase p00c_architecture_planner failed (non-critical): 'str' object has no attribute 'get'".
The s01 tests only passed because their fake p00 returned a dict.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aether_os.core.stack_profiles import get_profile
from aether_os.phases.p00_research import multimodal_intake
from aether_os.phases.p00_research import task_agent as p00
from aether_os.phases.p00c_architecture_planner import task_agent as p00c


class _FakeLLM:
    async def call_json(self, prompt, task_type="analysis"):
        return {"layout_patterns": {}, "must_have_features": []}


def test_p00_metadata_build_profile_is_a_dict_p00c_can_read(monkeypatch, tmp_path):
    profile = get_profile("go_microservices")

    async def classify(spec, domain):
        return profile

    async def parse(data):
        return data.get("raw_input", ""), "text"

    async def no_business_model(**kw):
        return None

    monkeypatch.setattr(multimodal_intake, "detect_and_parse_input", parse)
    monkeypatch.setattr(p00, "classify_build", classify)
    monkeypatch.setattr(p00, "load_pack", lambda domain: None)
    monkeypatch.setattr(p00, "generate_business_model", no_business_model)
    monkeypatch.setattr(p00._llm_client, "get_llm_client", lambda: _FakeLLM())
    monkeypatch.setenv("AUTONOMOUS_MODE", "true")

    pi = SimpleNamespace(input_data={"raw_input": "an order service", "domain": "unmapped_domain"},
                         domain="unmapped_domain")
    result = asyncio.run(p00.run(pi, [], tmp_path / "p00"))

    bp = result.metadata["build_profile"]
    assert isinstance(bp, dict)
    assert bp["name"] == profile.name and bp["architecture"] == profile.architecture

    # What the s01 supervisor does next: the merged context must be usable by p00c.
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: _FakeLLM())
    pi2 = SimpleNamespace(input_data={"build_profile": bp, "raw_input": "an order service"})
    out = asyncio.run(p00c.run(pi2, [], tmp_path / "p00c"))
    assert out.success
