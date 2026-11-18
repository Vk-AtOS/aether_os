"""KAN-111: dashboard/package-lock.json is tracked and matches package.json (npm ci in CI, deploy.sh, Dockerfile)."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "dashboard"


def test_lock_is_tracked_not_ignored_and_matches_package_json():
    lock = DASH / "package-lock.json"
    assert lock.exists()
    ignored = subprocess.run(["git", "check-ignore", "-q", str(lock)], cwd=ROOT).returncode == 0
    assert not ignored, "package-lock.json is git-ignored: npm ci cannot work on a fresh checkout"
    pkg = json.loads((DASH / "package.json").read_text())
    root = json.loads(lock.read_text())["packages"][""]
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        assert root.get(section, {}) == pkg.get(section, {}), f"lock out of sync with package.json ({section})"
