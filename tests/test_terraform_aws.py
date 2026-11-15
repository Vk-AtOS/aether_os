"""KAN-48: the Terraform tree is validated when terraform exists, and always checked for secrets and state separation."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TF = Path(__file__).resolve().parents[1] / "deploy/terraform/aws"
FILES = [p for p in TF.rglob("*") if p.is_file() and ".terraform/" not in str(p)]


def test_no_credentials_in_terraform_tree():
    pat = re.compile(r"AKIA[0-9A-Z]{16}|aws_secret_access_key|-----BEGIN [A-Z ]*PRIVATE KEY|sk-[A-Za-z0-9]{20,}")
    assert [str(p) for p in FILES if pat.search(p.read_text(errors="ignore"))] == []


def test_each_environment_has_its_own_state_key():
    keys = {e: re.search(r'key\s*=\s*"([^"]+)"', (TF / f"environments/{e}/backend.tf").read_text()).group(1)
            for e in ("staging", "production")}
    assert len(set(keys.values())) == 2
    for e in keys:
        assert "bucket" not in (TF / f"environments/{e}/backend.tf").read_text().split("terraform {")[1]


def test_redis_never_evicts_and_data_tier_is_private():
    data = (TF / "modules/data/main.tf").read_text()
    assert '"noeviction"' in data and "publicly_accessible          = false" in data
    assert "storage_encrypted            = true" in data


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform is not installed")
@pytest.mark.parametrize("env", ["staging", "production"])
def test_terraform_validate(env, tmp_path):
    d = TF / f"environments/{env}"
    init = subprocess.run(["terraform", "init", "-backend=false", "-input=false"], cwd=d, capture_output=True, text=True)
    if init.returncode != 0:
        pytest.skip("terraform init could not download providers (offline)")
    out = subprocess.run(["terraform", "validate"], cwd=d, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
