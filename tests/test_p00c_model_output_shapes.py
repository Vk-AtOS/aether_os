"""p00c must survive the service-map shapes real models return, not only the fake model's.

Run 09297aa3 failed p00c with "'str' object has no attribute 'get'". The immediate cause was a
str build_profile (see test_p00_build_profile_metadata.py); the planner also called .get() on
every services[] entry, so a list of names or JSON-in-a-string crashed it the same way.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from aether_os.phases.p00c_architecture_planner import task_agent as p00c
from aether_os.phases.p00c_architecture_planner.helpers import coerce_service_map, validate_service_map

_SVC = {"name": "auth-service", "lang": "go", "framework": "gin", "port": 8001,
        "owns_entities": ["User"], "communication": "rest", "db": "postgres", "critical": True}


def test_list_of_names_becomes_valid_services_with_unique_ports():
    raw = {"services": ["auth-service", "order-service", "billing-service"], "message_bus": "kafka"}
    sm = coerce_service_map(raw, "go")
    assert validate_service_map(sm) == []
    assert [s["name"] for s in sm["services"]] == ["auth-service", "order-service", "billing-service"]
    assert [s["port"] for s in sm["services"]] == [8001, 8002, 8003]
    assert all(s["lang"] == "go" and s["communication"] == "rest" for s in sm["services"])


def test_json_text_entries_and_missing_keys_are_handled():
    raw = {"services": [json.dumps(_SVC), {"name": "order-service", "port": "8002", "communication": "gRPC"},
                        "This service handles payments and refunds\nand more prose", 42, None]}
    sm = coerce_service_map(raw, "go")
    assert validate_service_map(sm) == []
    assert [s["name"] for s in sm["services"]] == ["auth-service", "order-service"]
    assert sm["services"][1]["port"] == 8002 and sm["services"][1]["communication"] == "grpc"
    assert sm["message_bus"] == ""


def test_top_level_list_and_json_string_replies():
    assert validate_service_map(coerce_service_map([_SVC], "go")) == []
    reply = "```json\n" + json.dumps({"services": [_SVC]}) + "\n```\nThis keeps auth isolated."
    assert validate_service_map(coerce_service_map(reply, "go")) == []


@pytest.mark.parametrize("raw", ["no json here", 3, None, {"services": "auth-service"}, {"services": [{"port": 8001}]}])
def test_unusable_replies_fail_validation_instead_of_crashing(raw):
    assert validate_service_map(coerce_service_map(raw, "go"))


def test_validate_service_map_rejects_non_dict_entries_without_crashing():
    errors = validate_service_map({"services": ["auth-service"], "message_bus": ""})
    assert errors == ["services[0]: must be an object, got str"]
    assert validate_service_map(["x"])


class _LLM:
    def __init__(self, reply):
        self.reply = reply

    async def call_json(self, prompt, task_type="analysis"):
        return self.reply


def _run(monkeypatch, tmp_path, build_profile, reply):
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: _LLM(reply))
    pi = SimpleNamespace(input_data={"build_profile": build_profile, "raw_input": "shop"})
    return asyncio.run(p00c.run(pi, [], tmp_path))


def test_run_with_list_of_names_uses_model_services(monkeypatch, tmp_path):
    out = _run(monkeypatch, tmp_path, {"architecture": "microservices", "backend_lang": "go"},
               {"services": ["auth-service", "catalog-service"]})
    assert out.success and out.metadata["service_count"] == 2 and not out.metadata["fallback"]


def test_run_with_profile_name_string_does_not_crash(monkeypatch, tmp_path):
    out = _run(monkeypatch, tmp_path, "go_microservices", {"services": [_SVC]})
    assert out.success and out.metadata["service_count"] == 1
