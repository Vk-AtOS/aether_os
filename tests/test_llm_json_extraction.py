"""Regression: real models put text after the JSON; parsers json.loads'ed the whole reply.

Run 09297aa3 (Nemotron via an OpenAI-compatible API) logged
"[spec_critique] direct JSON parse failed: Extra data: line 46 column 1" and then
"JSON extraction from prose failed: Extra data": a valid object followed by more text.
All of these go through core.llm.json_enforcer.extract_first_json now.
"""
from __future__ import annotations

import json

import pytest

from aether_os.core.council.council import _ERROR_RESULT, _parse_council_response
from aether_os.core.llm.json_enforcer import extract_first_json, extract_json, parse_llm_json
from aether_os.core.llm.token_counter import safe_parse_json
from aether_os.phases.p01_intake_requirements.spec_critique import _parse_critique_response

_CRITIQUE = {
    "issues": [{"category": "auth", "description": "no roles", "suggested_fix": "add roles"}],
    "improved_spec": "A shop. Admins manage {products}; customers order.",
}
_OBJ = json.dumps(_CRITIQUE, indent=2)

# Realistic replies seen from non-Claude models.
JSON_THEN_PROSE = _OBJ + "\n\nI focused on the auth gaps first because {roles} were undefined."
FENCED_THEN_EXPLANATION = (
    "Here is my review:\n\n```json\n" + _OBJ + "\n```\n\n"
    "**Explanation:** the spec never says who can delete an order {see above}."
)
TWO_OBJECTS = _OBJ + '\n{"issues": [], "improved_spec": "second pass"}'
PROSE_WITH_BRACES_FIRST = "Note {not json} and [also not]: " + _OBJ + "\nDone."


@pytest.mark.parametrize("reply", [JSON_THEN_PROSE, FENCED_THEN_EXPLANATION, TWO_OBJECTS, PROSE_WITH_BRACES_FIRST])
def test_first_complete_object_is_returned(reply):
    with pytest.raises(json.JSONDecodeError):
        json.loads(reply)  # the old first step
    assert extract_first_json(reply, expect=dict) == _CRITIQUE
    assert json.loads(extract_json(reply)) == _CRITIQUE
    assert parse_llm_json(reply) == _CRITIQUE


def test_double_encoded_json_string_is_unwrapped():
    assert extract_first_json(json.dumps(_OBJ), expect=dict) == _CRITIQUE


def test_list_is_not_mistaken_for_its_first_element_when_object_expected():
    with pytest.raises(ValueError):
        extract_first_json('[{"a": 1}, {"b": 2}] trailing', expect=dict)
    assert extract_first_json('[{"a": 1}] trailing') == [{"a": 1}]


def test_truncated_object_does_not_yield_a_nested_fragment():
    truncated = '{"services": [{"name": "auth", "port": 8001}, {"name": "ord'
    with pytest.raises(ValueError):
        extract_first_json(truncated, expect=dict)
    assert safe_parse_json(truncated)["parse_error"] is True


def test_no_json_at_all():
    with pytest.raises(ValueError):
        extract_first_json("I cannot help with that.")
    assert parse_llm_json("I cannot help with that.", fallback={}) == {}


@pytest.mark.parametrize("reply", [JSON_THEN_PROSE, FENCED_THEN_EXPLANATION, TWO_OBJECTS])
def test_spec_critique_uses_the_models_answer(reply):
    out = _parse_critique_response(reply, "orig")
    assert out["issues"] == _CRITIQUE["issues"]
    assert out["improved_spec"] == _CRITIQUE["improved_spec"]


def test_spec_critique_wrong_value_types_keep_original():
    out = _parse_critique_response('{"issues": "one issue", "improved_spec": {"x": 1}} ok', "orig")
    assert out == {"issues": ["one issue"], "improved_spec": "orig"}


def test_council_reply_followed_by_reasoning():
    verdict = {"verdict": "PASS", "score": 0.9, "reason": "ok", "suggestions": []}
    reply = "```json\n" + json.dumps(verdict) + "\n```\nReasoning: the spec {is} complete."
    assert _parse_council_response(reply) == verdict
    assert _parse_council_response("no json here") == _ERROR_RESULT


def test_safe_parse_json_keeps_whole_object_not_nested_one():
    # Old fallback regex \{[^{}]*\} returned {"name": "auth"} (the first brace-free object).
    reply = '{"services": [{"name": "auth"}], "message_bus": ""}\n\nThis design separates auth.'
    assert safe_parse_json(reply) == {"services": [{"name": "auth"}], "message_bus": ""}
