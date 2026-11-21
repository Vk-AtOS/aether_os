"""KAN-102/111: the Helm schema job runs BEFORE the API rolls out (a post hook deadlocked `helm install --wait`: the API
refuses to start on a schema that is not at head, so the release never became Ready and the hook never started)."""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "helm" / "aetheros"
BASE = ["--set", "config.AETHER_PREVIEW_ORIGIN=https://preview.example.com"]
EXTERNAL_DB = ["--set", "postgresql.enabled=false", "--set", "secrets.DATABASE_URL=postgresql://u:p@db/aether"]

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*args):
    out = subprocess.run(["helm", "template", "r", str(CHART), "--show-only", "templates/migrate-job.yaml", *BASE, *args],
                         check=True, capture_output=True, text=True, timeout=60).stdout
    return {d["kind"]: d for d in yaml.safe_load_all(out) if d}


def _ann(doc):
    return doc["metadata"]["annotations"]


def test_migrate_job_is_a_pre_install_pre_upgrade_hook_with_an_external_database():
    docs = _render(*EXTERNAL_DB)
    job, secret = docs["Job"], docs["Secret"]
    assert _ann(job)["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert _ann(job)["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"
    # what the job reads is created first by a lower-weight hook (the release's own Secret/ConfigMap do not exist yet)
    assert _ann(secret)["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert int(_ann(secret)["helm.sh/hook-weight"]) < int(_ann(job)["helm.sh/hook-weight"])
    refs = [e["secretRef"]["name"] for e in job["spec"]["template"]["spec"]["containers"][0]["envFrom"]]
    assert refs == [secret["metadata"]["name"]]
    assert {"DATABASE_URL", "AETHER_FIELD_KEY"} <= set(secret["stringData"])


def test_bundled_postgres_first_install_cannot_be_pre_install_but_every_upgrade_is_pre_upgrade():
    # the sub-chart database does not exist before the first install, so only the first install falls back to post-install
    assert _ann(_render()["Job"])["helm.sh/hook"] == "post-install,pre-upgrade"
    assert "pre-upgrade" in _ann(_render()["Job"])["helm.sh/hook"]


def test_hook_phase_can_be_overridden():
    assert _ann(_render("--set", "migrate.hook=pre-install\\,pre-upgrade")["Job"])["helm.sh/hook"] == "pre-install,pre-upgrade"
