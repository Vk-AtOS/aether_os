"""KAN-109: the generated canary runs beside the stable deployment and fails closed without data."""
import importlib.util
from pathlib import Path

import pytest

from aether_os.phases.p21_sre_agent.sre_generators import write_sre_canary_runner


@pytest.fixture()
def canary(tmp_path, monkeypatch):
    write_sre_canary_runner(tmp_path, "shop", "prod")
    spec = importlib.util.spec_from_file_location("canary_runner", tmp_path / "canary_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    calls = []
    state = {"stable": {"metadata": {"name": "shop"}, "spec": {"replicas": 9, "selector": {"matchLabels": {"app": "shop"}},
             "template": {"metadata": {"labels": {"app": "shop"}}, "spec": {"containers": [{"name": "shop", "image": "shop:v1"}]}}}}}

    def k8s(method, path, body=None, patch=False):
        calls.append((method, path.rsplit("/", 1)[-1], body))
        if method == "GET":
            return {**state["stable"], "status": {"readyReplicas": 99, "updatedReplicas": 99}}
        return {}

    monkeypatch.setattr(mod, "_k8s", k8s)
    return mod, calls


def _patched_stable(calls):
    return [c for c in calls if c[0] == "PATCH" and c[1] == "shop"]


def test_canary_gets_its_share_and_stable_is_untouched_when_metrics_are_missing(canary, monkeypatch):
    mod, calls = canary
    monkeypatch.setattr(mod, "_query", lambda q: None)               # Prometheus down / no traffic
    assert mod.run_canary("shop:v2") is False
    created = [c for c in calls if c[0] == "POST"][0][2]
    assert created["metadata"]["name"] == "shop-canary" and created["spec"]["replicas"] == 1   # 9 stable * 10/90
    assert created["spec"]["template"]["spec"]["containers"][0]["image"] == "shop:v2"
    assert not _patched_stable(calls)                                 # the stable image never changed
    assert calls[-1][0] == "DELETE"                                   # canary removed


def test_bad_metrics_roll_back_good_metrics_promote(canary, monkeypatch):
    mod, calls = canary
    monkeypatch.setattr(mod, "_query", lambda q: 50.0 if "status" in q else 100.0)
    assert mod.run_canary("shop:v2") is False and not _patched_stable(calls)
    calls.clear()
    monkeypatch.setattr(mod, "_query", lambda q: 0.2 if "status" in q else 120.0)
    assert mod.run_canary("shop:v2") is True
    assert _patched_stable(calls)[0][2]["spec"]["template"]["spec"]["containers"][0]["image"] == "shop:v2"
    assert calls[-1][0] == "DELETE"


def test_weight_is_used_and_no_kubectl():
    src = (Path(__file__).resolve().parent.parent / "phases/p21_sre_agent/canary_src.py").read_text()
    assert "CANARY_WEIGHT" in src and "canary_replicas(" in src and "kubectl" not in src.split('"""', 2)[2]
