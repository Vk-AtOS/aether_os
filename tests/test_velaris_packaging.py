"""KAN-112: the AetherOS side of running Velaris next to AetherOS: key from env, compose/k8s/helm wiring, signed smoke."""
import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aether_os.core.velaris.client import VelarisClient, VelarisUnavailable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("velaris_smoke", ROOT / "scripts/velaris_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _pem() -> str:
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("VELARIS_API_URL", "http://velaris:8730")
    monkeypatch.setenv("VELARIS_API_SECRET", "s" * 32)
    monkeypatch.delenv("VELARIS_IDENTITY_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VELARIS_IDENTITY_PRIVATE_KEY_PEM", raising=False)


def test_identity_key_can_come_from_env_as_pem(env, monkeypatch):
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY_PEM", _pem())
    assert VelarisClient.from_env() is not None
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY_PEM", "not a pem")
    with pytest.raises(VelarisUnavailable):
        VelarisClient.from_env()                       # garbage fails closed, it is not silently ignored


def test_path_wins_over_pem_and_missing_key_is_not_connected(env, monkeypatch, tmp_path):
    with pytest.raises(VelarisUnavailable, match="not connected"):
        VelarisClient.from_env()
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY_PEM", _pem())
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY", str(tmp_path / "missing.pem"))
    with pytest.raises(VelarisUnavailable):
        VelarisClient.from_env()                       # the path was given, so it is the one used (and it is unreadable)


def _client(handler):
    return VelarisClient("http://velaris.test", b"s" * 32, Ed25519PrivateKey.generate(), transport=httpx.MockTransport(handler))


def test_smoke_passes_on_200_and_sends_signed_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})
    ok, why = asyncio.run(smoke.check(_client(handler), "org-1"))
    assert ok and "200" in why
    assert {"x-velaris-signature", "x-velaris-identity", "x-velaris-nonce", "x-velaris-timestamp"} <= set(seen)


def test_smoke_fails_on_wrong_organisation_refusal_and_on_unreachable():
    refuse = lambda r: httpx.Response(403, json={"error": {"code": "wrong_organisation", "message": "x"}})  # noqa: E731
    ok, why = asyncio.run(smoke.check(_client(refuse), "other"))
    assert not ok and "403" in why and "wrong_organisation" in why

    def down(request):
        raise httpx.ConnectError("refused")
    ok, why = asyncio.run(smoke.check(_client(down), "org-1"))
    assert not ok and "unavailable" in why


def test_smoke_script_skips_when_velaris_is_not_configured(monkeypatch, capsys):
    for k in ("VELARIS_API_URL", "VELARIS_API_SECRET", "VELARIS_IDENTITY_PRIVATE_KEY", "VELARIS_IDENTITY_PRIVATE_KEY_PEM"):
        monkeypatch.delenv(k, raising=False)
    assert smoke.main(["--org", "o"]) == 2 and "SKIP" in capsys.readouterr().out


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]


def test_compose_velaris_is_internal_only_read_only_and_org_scoped():
    s = _compose()
    v, pub = s["velaris"], s["velaris_public"]
    assert "ports" not in v and v["expose"] == ["8730"]                         # the API port is never published
    assert pub["ports"] == ["127.0.0.1:8731:8731"]                              # the public app: loopback, nginx in front
    for svc in (v, pub):
        assert svc["profiles"] == ["velaris"] and svc["read_only"] is True and svc["cap_drop"] == ["ALL"]
    text = (ROOT / "docker-compose.yml").read_text()
    assert "VELARIS_ORG:?" in text and "velaris_identity.pub.pem:/run/identity/velaris_identity.pub.pem:ro" in text
    assert v["volumes"][0] == "velaris_data:/data"                              # restart keeps data
    api_env = s["api"]["environment"]
    assert "VELARIS_IDENTITY_PRIVATE_KEY_PEM" in api_env and "VELARIS_IDENTITY_PRIVATE_KEY" not in api_env
    assert s["api"]["healthcheck"]["test"][-1].endswith("/healthz") and s["api"]["stop_grace_period"] == "60s"


def test_k8s_and_helm_carry_the_pem_key_not_a_path_and_label_the_gateway_pods():
    for f in ("deploy/kubernetes/api.yaml", "deploy/kubernetes/secret.yaml", "helm/aetheros/values.yaml",
              "helm/aetheros/templates/secret.yaml"):
        t = (ROOT / f).read_text()
        assert "VELARIS_IDENTITY_PRIVATE_KEY_PEM" in t
        assert "VELARIS_IDENTITY_PRIVATE_KEY:" not in t.replace("VELARIS_IDENTITY_PRIVATE_KEY_PEM:", "")
    assert "app.kubernetes.io/component: gateway" in (ROOT / "helm/aetheros/templates/deployment.yaml").read_text()


def test_deploy_script_runs_the_signed_smoke_when_velaris_is_configured():
    sh = (ROOT / "deploy/deploy.sh").read_text()
    assert "scripts/velaris_smoke.py" in sh and "VELARIS_API_URL" in sh
