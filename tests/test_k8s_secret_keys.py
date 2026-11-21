"""KAN-111/KAN-102: the Kubernetes manifests reference only Secret keys that secret.yaml defines, and the ledger signing key
is delivered as a file the checkpoint signer will accept."""
from pathlib import Path

import yaml

K8S = Path(__file__).resolve().parents[1] / "deploy" / "kubernetes"


def _docs(name):
    return list(yaml.safe_load_all((K8S / name).read_text()))


def test_every_secretkeyref_key_exists_in_secret_yaml():
    defined = set(_docs("secret.yaml")[0]["stringData"])
    wanted = set()
    for fname in ("api.yaml", "migrate-job.yaml"):
        for doc in _docs(fname):
            spec = (doc.get("spec") or {}).get("template", {}).get("spec", {})
            for c in spec.get("containers", []) + spec.get("initContainers", []):
                for env in c.get("env", []):
                    ref = (env.get("valueFrom") or {}).get("secretKeyRef")
                    if ref and not ref.get("optional"):
                        wanted.add(ref["key"])
    assert wanted - defined == set()


def test_ledger_signing_key_is_a_0600_file_for_every_replica():
    dep = next(d for d in _docs("api.yaml") if d["kind"] == "Deployment")
    spec = dep["spec"]["template"]["spec"]
    api = next(c for c in spec["containers"] if c["name"] == "api")
    env = {e["name"]: e.get("value") for e in api["env"]}
    assert env["AETHER_LEDGER_SIGNING_KEY"] == "/ledger/ledger_signing_key.pem"
    init = next(c for c in spec["initContainers"] if c["name"] == "ledger-key")
    assert "chmod 600" in init["command"][-1]
    assert "AETHER_LEDGER_SIGNING_KEY_PEM" in _docs("secret.yaml")[0]["stringData"]
