"""KAN-247: s07 always starts the generated app and its gate blocks when the app does not answer HTTP.

The sandbox is not available here: the app start, the HTTP sender and the healer are fakes, so these tests drive
the decision rules only (stages/s07_healing/run_verdict.py and the s07 supervisor).
"""
import asyncio
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.stages.s07_healing import run_verdict as rv
from aether_os.stages.s07_healing import supervisor as s07

_LIVE_OK = {"phases": {k: {"success": True, "issues": []} for k in rv.LIVE_LAYERS}, "skipped_phases": []}
_ENDPOINTS_OK = {"passed": True, "checks": [], "failures": []}


def _probe(l1=True, endpoints=_ENDPOINTS_OK, tests=_LIVE_OK, **extra):
    return {"l1_passed": l1, "live_tests": {"endpoints": endpoints, "tests": tests} if l1 else None, **extra}


def _heal_meta(**probe_kw):
    return {"status": "all_tests_passing", "attempts": 1, "quality_probe": _probe(**probe_kw)}


# ── s07 verdict rules ────────────────────────────────────────────────────────

def test_verdict_passes_only_when_the_app_started_and_endpoints_answered():
    v = rv.decide(_heal_meta())
    assert v["passed"] and v["app_started"] and v["not_verified"] == []


def test_verdict_fails_when_the_app_never_started():
    v = rv.decide(_heal_meta(l1=False, reason="server_startup_timeout"))
    assert not v["passed"] and "did not start" in v["reasons"][0] and "server_startup_timeout" in v["reasons"][0]
    # the deferred live tests are reported as not run, never silently dropped
    assert len(v["not_verified"]) == 3 and all("not run" in n for n in v["not_verified"])


def test_verdict_fails_when_the_probe_never_ran():
    v = rv.decide({"status": "all_tests_passing", "attempts": 1})
    assert not v["passed"] and "never ran" in v["reasons"][0]


def test_verdict_fails_when_a_spec_endpoint_is_5xx_or_missing():
    bad = {"passed": False, "failures": ["GET /api/tasks returned 500"]}
    v = rv.decide(_heal_meta(endpoints=bad))
    assert not v["passed"] and "/api/tasks returned 500" in v["reasons"][0]
    assert not rv.decide(_heal_meta(endpoints=None))["passed"]           # endpoints never probed


def test_verdict_fails_when_healing_is_exhausted():
    meta = {**_heal_meta(), "status": "max_attempts_reached", "self_healing_exhausted": True}
    assert not rv.decide(meta)["passed"]


def test_live_layers_failed_or_not_run_are_not_verified_but_do_not_fail_the_verdict():
    tests = {"phases": {"performance_testing": {"success": True, "issues": []},
                        "accessibility_testing": {"success": False, "issues": ["3 violations"]}},
             "skipped_phases": ["e2e_testing: playwright missing"],
             "perf_results": {"skipped": True, "data": {"reason": "no backend_port"}}}
    v = rv.decide(_heal_meta(tests=tests))
    assert v["passed"]
    assert v["live_layers"]["performance_testing"].startswith("not run: no backend_port")
    assert v["live_layers"]["accessibility_testing"].startswith("failed: 3 violations")
    assert v["live_layers"]["e2e_testing"].startswith("not run: e2e_testing: playwright missing")
    assert len(v["not_verified"]) == 3


def test_e2e_with_failing_tests_is_failed():
    tests = {**_LIVE_OK, "e2e_results": {"passed": 2, "failed": 1}}
    assert rv.live_layer_status(tests)["e2e_testing"].startswith("failed")


# ── endpoint probe (fake HTTP sender) ────────────────────────────────────────

def _sender(statuses, seen):
    async def send(method, url, body, headers):
        seen.append((method, url, (headers or {}).get("Authorization")))
        if url.endswith("/api/auth/login"):
            return 200, {"access_token": "tok"}
        if url.endswith("/api/auth/register"):
            return 201, {}
        status = statuses.get(url.split("http://app")[1])
        if status is None:
            raise ConnectionError("refused")
        return status, []
    return send


def _run_probe(statuses):
    seen = []
    out = asyncio.run(rv.probe_endpoints("http://app", ["Task", {"name": "Project", "table": "projects"}, "User"],
                                         _sender(statuses, seen), "pw"))
    return out, seen


def test_probe_hits_health_and_every_spec_list_endpoint_with_a_token():
    out, seen = _run_probe({"/health": 200, "/api/tasks": 200, "/api/projects": 401})
    assert out["passed"] and out["authenticated"] and out["spec_paths"] == ["/api/tasks", "/api/projects"]
    assert ("GET", "http://app/api/tasks", "Bearer tok") in seen      # the handler is reached, not only the guard


def test_probe_fails_on_5xx_404_bad_health_or_no_answer():
    assert not _run_probe({"/health": 200, "/api/tasks": 500, "/api/projects": 200})[0]["passed"]
    assert not _run_probe({"/health": 200, "/api/tasks": 404, "/api/projects": 200})[0]["passed"]
    assert not _run_probe({"/health": 503, "/api/tasks": 200, "/api/projects": 200})[0]["passed"]
    out, _ = _run_probe({"/health": 200, "/api/tasks": 200})            # /api/projects: connection refused
    assert not out["passed"] and "no answer" in out["failures"][0]


# ── s07 stage: the static-score shortcut never skips the app start ───────────

def _stage(monkeypatch, tmp_path, ctx, probe_meta, heal_meta=None):
    calls = {"probe": 0, "heal": 0}

    async def fake_probe(pi, out, hook):
        calls["probe"] += 1
        return probe_meta

    async def fake_heal(pi, mem, out, live_hook=None):
        calls["heal"] += 1
        return TaskResult(output_path=str(out), confidence=0.9, metadata=dict(heal_meta or _heal_meta()))

    monkeypatch.setattr(s07, "_probe_only", fake_probe)
    monkeypatch.setattr("aether_os.phases.p07b_self_healing.task_agent.run", fake_heal)
    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path / "o"))
    sup = s07.HealingStageSupervisor()
    res = asyncio.run(sup.run_task(SimpleNamespace(project_id="p", run_id="r", input_data=ctx), []))
    gate = asyncio.run(sup.validate_gate(res, None))
    return res, gate, calls


_GREEN = {"s07_healing_done": True, "test_results": {"passed": 7, "failed": 0}}


def test_high_static_score_still_starts_the_app_and_skips_only_the_repair_loop(monkeypatch, tmp_path):
    res, gate, calls = _stage(monkeypatch, tmp_path, _GREEN, {"status": "probe_only", "quality_probe": _probe()})
    assert calls == {"probe": 1, "heal": 0}
    assert res.metadata["healing_passed"] is True and gate.passed


def test_high_static_score_but_app_down_runs_the_repair_loop(monkeypatch, tmp_path):
    down = {"status": "probe_only", "quality_probe": _probe(l1=False, reason="crash")}
    _, gate, calls = _stage(monkeypatch, tmp_path, _GREEN, down)
    assert calls == {"probe": 1, "heal": 1} and gate.passed


def test_high_static_score_with_failing_unit_tests_goes_to_the_repair_loop(monkeypatch, tmp_path):
    ctx = {"s07_healing_done": True, "test_results": {"passed": 3, "failed": 2}}
    _, _, calls = _stage(monkeypatch, tmp_path, ctx, None)
    assert calls == {"probe": 0, "heal": 1}


def test_s07_gate_blocks_when_the_app_does_not_start(monkeypatch, tmp_path):
    down = _heal_meta(l1=False, reason="server_startup_timeout")
    res, gate, _ = _stage(monkeypatch, tmp_path, {}, None, heal_meta=down)
    assert res.metadata["healing_passed"] is False and res.success is False
    assert not gate.passed and "did not start" in gate.issues[0]
    assert res.metadata["live_test_results"]["skipped"] is True


def test_s07_gate_passes_but_discloses_live_tests_that_did_not_run(monkeypatch, tmp_path):
    tests = {"phases": {}, "skipped_phases": []}
    res, gate, _ = _stage(monkeypatch, tmp_path, {}, None, heal_meta=_heal_meta(tests=tests))
    assert gate.passed and len(res.metadata["not_verified"]) == 3
    assert any("e2e_testing: not run" in i for i in gate.issues)


def test_s07_does_not_retry_its_whole_repair_loop():
    assert s07.HealingStageSupervisor.max_retries == 1
