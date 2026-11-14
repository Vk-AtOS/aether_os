"""KAN-99/KAN-109: generated SRE agent needs no kubectl, and its webhook is authenticated."""
import asyncio
import importlib.util
import py_compile
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from types import SimpleNamespace

import pytest
import yaml

from aether_os.phases.p21_sre_agent import task_agent


@pytest.fixture()
def out(tmp_path):
    pi = SimpleNamespace(input_data={"project_name": "demo", "domain": "fintech"})
    assert asyncio.run(task_agent.run(pi, [], tmp_path)).success
    for f in tmp_path.rglob("*.py"):
        py_compile.compile(str(f), doraise=True)
    return tmp_path


def _load(path, name):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cronjob_yaml_valid_and_script_configmap_created(out):
    docs = list(yaml.safe_load_all((out / "k8s" / "sre-agent-cronjob.yaml").read_text()))
    cm = next(d for d in docs if d["kind"] == "ConfigMap")
    assert cm["metadata"]["name"] == "demo-sre-scripts"
    assert "def check_and_remediate" in cm["data"]["sre_failure_classifier.py"]


def test_no_kubectl_binary_or_subprocess_in_remediation(out):
    for f in (out / "scripts" / "sre_failure_classifier.py", out / "sre" / "remediation_generator.py"):
        assert "subprocess" not in f.read_text()


def test_remediation_goes_through_api_and_refuses_other_commands(out, monkeypatch):
    mod = _load(out / "sre" / "remediation_generator.py", "rg_test")
    calls = []
    monkeypatch.setattr(mod, "_k8s_patch", lambda path, body, ct: calls.append((path, body, ct)))
    assert mod.apply_remediation("kubectl scale deployment/demo --replicas=3 -n prod", "a")
    assert calls[-1][0] == "/apis/apps/v1/namespaces/prod/deployments/demo/scale"
    assert mod.apply_remediation("kubectl rollout restart deployment/demo -n prod", "a")
    assert "restartedAt" in str(calls[-1][1])
    n = len(calls)
    assert mod.apply_remediation("kubectl delete secret demo-tls -n prod", "a") is False
    assert len(calls) == n
    assert mod.generate_remediation("certificate", "demo", "prod") is None


def test_rbac_cannot_touch_secrets(out):
    docs = list(yaml.safe_load_all((out / "sre" / "manifests" / "sre-rbac.yaml").read_text()))
    for d in docs:
        for rule in d.get("rules", []):
            assert "secrets" not in rule["resources"]
            assert "delete" not in rule["verbs"]


def test_webhook_requires_bearer_token(out, monkeypatch):
    monkeypatch.setenv("WEBHOOK_TOKEN", "s3cret")
    op = _load(out / "sre" / "operator.py", "op_test")
    srv = HTTPServer(("127.0.0.1", 0), op.AlertWebhookHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/webhook"

    def post(auth):
        req = urllib.request.Request(url, data=b'{"alerts": []}', method="POST",
                                     headers={"Authorization": auth} if auth else {})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert post(None) == 401 and post("Bearer wrong") == 401
        assert post("Bearer s3cret") == 200
        op.WEBHOOK_TOKEN = ""
        assert post("Bearer ") == 401  # unset token fails closed
    finally:
        srv.shutdown()
