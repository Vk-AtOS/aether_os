"""KAN-183/192/194: non-product files stay out of git and out of the source tree."""
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = ("snapshots/", "_snapshot.md", "vkatos_deploy/", "playwright_audit_report.md",
             "uv.lock", "plans2.md", "settings-deep.yml", "VENDOR_MANIFEST.json")


def test_tests_do_not_write_guardian_dumps_into_the_repo():
    d = pathlib.Path(os.environ["GUARDIAN_SNAPSHOT_DIR"]).resolve()
    assert ROOT not in d.parents and d != ROOT


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_no_non_product_files_tracked():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    bad = [f for f in files if f and any(f.endswith(x) or x in f for x in FORBIDDEN)]
    assert not bad, bad
