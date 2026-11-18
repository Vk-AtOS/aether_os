"""KAN-92: a per-process encryption key is for development and test only; staging and production need AETHER_FIELD_KEY."""
import pytest

from aether_os.core import encryption


@pytest.mark.parametrize("env", ["staging", "production", "prod", "preview", "Production"])
def test_deployed_environments_refuse_an_ephemeral_key(monkeypatch, env):
    monkeypatch.delenv("AETHER_FIELD_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.setattr(encryption, "_fernet", None)
    with pytest.raises(RuntimeError, match="AETHER_FIELD_KEY"):
        encryption.encrypt("x")


@pytest.mark.parametrize("env", ["development", "test"])
def test_dev_and_test_still_work_without_a_key(monkeypatch, env):
    monkeypatch.delenv("AETHER_FIELD_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.setattr(encryption, "_fernet", None)
    assert encryption.decrypt(encryption.encrypt("hello")) == "hello"


def test_every_deployed_mode_sets_the_environment_variable():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("docker-compose.yml", "docker-compose.staging.yml", "deploy/kubernetes/configmap.yaml",
                "helm/aetheros/values.yaml"):
        assert "ENVIRONMENT" in (root / rel).read_text(), rel
