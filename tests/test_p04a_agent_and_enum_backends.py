"""p04a builds, imports and serves two specs that used to fail (KAN-253, KAN-264, KAN-276).

* a clinic booking spec whose day_of_week enum has the integer values 0-6 (run e53e5f12: refused with a message that
  blamed quotes and backslashes);
* an agent spec: src/agent.py was written but its router was never mounted, the LLM client could not use an
  OpenAI-compatible endpoint, web_search was a stub and its source did not even compile.
Each generated app runs in a subprocess (it has modules named main, models, auth, database).
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from aether_os.phases.p04a_backend_codegen import helpers, task_agent
from aether_os.phases.p04a_backend_codegen.pre_gen_validator import check_identifiers, coerce_enum_values

CLINIC_IR = {
    "domain": "healthcare", "app_name": "Clinic",
    "entities": [{"name": "Appointment", "table": "appointments", "fields": [
        {"name": "patient_name", "type": "string", "nullable": False},
        {"name": "day_of_week", "type": "enum", "enum_values": [0, 1, 2, 3, 4, 5, 6]},
        {"name": "status", "type": "enum", "enum_values": ["booked", "done"]}]}],
    "business_rules": [],
    "permissions": [{"role": "admin", "entity": "Appointment", "actions": ["read", "create", "update", "delete"]}],
}
AGENT_IR = {
    "domain": "general", "app_name": "Helper",
    "entities": [{"name": "Note", "table": "notes", "fields": [{"name": "title", "type": "string", "nullable": False}]}],
    "business_rules": [], "permissions": [],
}


def build(tmp_path, monkeypatch, ir, **extra):
    async def no_smoke(src_dir, emit):
        return {"passed": True, "errors": [], "check_imports": helpers._check_imports(src_dir), "skipped": True}
    monkeypatch.setattr(task_agent, "_smoke_test", no_smoke)
    monkeypatch.setenv("ENVIRONMENT", "test")
    (tmp_path / "domain_ir.json").write_text(json.dumps(ir))
    entities = [{"name": e["name"], "table": e["table"],
                 "fields": [{"name": f["name"], "type": f["type"]} for f in e["fields"]]} for e in ir["entities"]]
    data = {"project_name": ir["app_name"], "domain": ir["domain"], "entities": entities,
            "domain_ir_path": str(tmp_path / "domain_ir.json"), **extra}
    result = asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "app"))
    return result, tmp_path / "app"


def run_in_app(app_dir, script, **env):
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    runner = ("import json, os, sys\napp_dir = sys.argv[1]\nos.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, 'src'))\n"
              "os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + os.path.join(app_dir, 't.db')\nimport main\n"
              "from fastapi.testclient import TestClient\nout = {}\n" + script + "\nprint('RESULT ' + json.dumps(out))\n")
    full_env = {**os.environ, "ADMIN_PASSWORD": "Test-only-Admin-9z", "ENVIRONMENT": "test",
                "PYTHONDONTWRITEBYTECODE": "1", **env}
    p = subprocess.run([sys.executable, "-c", runner, str(app_dir)], capture_output=True, text=True, env=full_env,
                       timeout=180, cwd=str(app_dir))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"generated app did not run:\n{p.stdout[-800:]}\n{p.stderr[-2000:]}"
    return json.loads(line[7:])


# ── KAN-253: integer enum values ─────────────────────────────────────────────────────────────────────────

def test_integer_enum_values_pass_the_validator_and_unsafe_ones_get_the_real_reason():
    ok = [{"name": "A", "table": "a", "fields": [{"name": "d", "enum_values": [0, 1, 2.5, True, "x"]}]}]
    assert check_identifiers(ok) == []
    bad = [{"name": "A", "table": "a", "fields": [{"name": "d", "enum_values": ["it's", None, ["x"], "a\nb"]}]}]
    errors = check_identifiers(bad)
    assert len(errors) == 4
    assert "quote" in errors[0] and "NoneType" in errors[1] and "list" in errors[2] and "control character" in errors[3]
    assert not any("quote, backslash or control character" in e for e in errors[1:3])   # wrong reason for a non-text value
    assert coerce_enum_values([0, 1, "x", True]) == ["0", "1", "x", "True"]


def test_clinic_booking_backend_with_integer_day_of_week_builds_imports_and_serves(tmp_path, monkeypatch):
    result, app = build(tmp_path, monkeypatch, CLINIC_IR)
    assert result.success, result
    assert result.metadata["smoke_test"]["check_imports"] == []
    models = (app / "src" / "models.py").read_text()
    ast.parse(models)
    assert "'0', '1', '2', '3', '4', '5', '6'" in models        # stored as the text of the String column, not bare ints
    seed = (app / "src" / "seed.py").read_text()
    assert "day_of_week='0'" in seed and "day_of_week=0," not in seed        # seeded as text for the String column
    out = run_in_app(app, r'''
with TestClient(main.app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
    a = {"Authorization": "Bearer " + r.json()["access_token"]}
    out["create"] = c.post("/api/appointments", headers=a, json={"patient_name": "P", "day_of_week": "3", "status": "booked"}).status_code
    r = c.get("/api/appointments", headers=a)
    out["list"] = r.status_code
    out["days"] = sorted({i["day_of_week"] for i in r.json()["items"]})
''')
    assert out["create"] == 201 and out["list"] == 200 and out["days"]


# ── KAN-264 / KAN-276: the agent backend ─────────────────────────────────────────────────────────────────

@pytest.fixture
def agent_app(tmp_path, monkeypatch):
    result, app = build(tmp_path, monkeypatch, AGENT_IR, build_types=["agentic_ai"],
                        raw_input="an AI agent that answers questions with tools")
    assert result.success, result
    return app


def test_agent_backend_compiles_mounts_the_router_and_documents_its_env(agent_app):
    for f in agent_app.rglob("*.py"):
        compile(f.read_text(), str(f), "exec")
    main_py = (agent_app / "src" / "main.py").read_text()
    assert "from agent import router" in main_py and "include_router(_agent_router" in main_py
    req = (agent_app / "requirements.txt").read_text()
    assert "openai" in req and "sse-starlette" not in req          # pattern packages used to be overwritten away
    example = (agent_app / ".env.example").read_text()
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        assert name in example
    code = (agent_app / "src" / "agent.py").read_text()
    assert "stub" not in code.lower() and "base_url=base_url" in code


_AGENT_SCRIPT = r'''
import types
try:
    import openai
except ImportError:                      # CI has no openai package: a stand-in that records what the app passes it
    openai = types.ModuleType("openai")
    openai.AsyncOpenAI = lambda api_key, base_url=None: types.SimpleNamespace(api_key=api_key, base_url=base_url)
    sys.modules["openai"] = openai
import agent

class FakeCompletions:
    def __init__(self): self.calls = []
    async def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:           # first turn: ask for a tool
            fn = types.SimpleNamespace(name="calculate", arguments='{"expression": "6 * 7"}')
            msg = types.SimpleNamespace(content=None, tool_calls=[types.SimpleNamespace(id="c1", function=fn)])
        else:                              # second turn: answer from the tool result
            tool_msg = [m for m in kw["messages"] if m["role"] == "tool"][-1]
            msg = types.SimpleNamespace(content="The answer is " + tool_msg["content"], tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

fake = FakeCompletions()
client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=fake))
with TestClient(main.app, raise_server_exceptions=False) as c:
    out["anon"] = c.post("/api/agent/run", json={"messages": [{"role": "user", "content": "hi"}]}).status_code
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
    a = {"Authorization": "Bearer " + r.json()["access_token"]}
    body = {"messages": [{"role": "user", "content": "what is 6*7"}]}
    out["no_llm_env"] = c.post("/api/agent/run", headers=a, json=body).status_code      # LLM_* unset: honest 503
    os.environ["LLM_API_KEY"] = "fake-key"; os.environ["LLM_BASE_URL"] = "http://llm.invalid/v1"
    built = agent._build_llm_client()
    out["base_url"] = str(built[1].base_url); out["model"] = built[2]
    agent._build_llm_client = lambda: ("openai", client, "fake-model")
    r = c.post("/api/agent/run", headers=a, json=body)
    out["run"] = r.status_code
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    out["types"] = [e["type"] for e in events]
    out["tool_result"] = next(e["content"] for e in events if e["type"] == "tool_result")
    out["response"] = next(e["content"] for e in events if e["type"] == "response")
    cid = events[-1].get("conversation_id")
    out["tools_offered"] = sorted(t["function"]["name"] for t in fake.calls[0]["tools"])
    out["blank"] = c.post("/api/agent/run", headers=a, json={"messages": []}).status_code
    out["list"] = c.get("/api/agent/conversations", headers=a).json()
    out["get"] = c.get(f"/api/agent/conversations/{cid}", headers=a).status_code
    out["delete"] = c.delete(f"/api/agent/conversations/{cid}", headers=a).status_code
    out["gone"] = c.get(f"/api/agent/conversations/{cid}", headers=a).status_code
'''


def test_generated_agent_app_imports_and_runs_with_a_mocked_llm(agent_app):
    out = run_in_app(agent_app, _AGENT_SCRIPT)
    assert out["anon"] == 401                                    # the agent spends the owner's LLM budget: sign-in required
    assert out["no_llm_env"] == 503
    assert out["base_url"].startswith("http://llm.invalid/v1") and out["model"] == "gpt-4o-mini"
    assert out["run"] == 200
    assert out["types"] == ["tool_call", "tool_result", "response", "done"]
    assert out["tool_result"] == "42" and out["response"] == "The answer is 42"
    assert out["tools_offered"] == ["calculate", "get_current_time"]    # no web_search without a configured provider
    assert out["blank"] == 422
    assert out["list"]["items"] and out["list"]["items"][0]["message_count"] == 2
    assert (out["get"], out["delete"], out["gone"]) == (200, 204, 404)
