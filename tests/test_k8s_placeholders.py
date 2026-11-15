"""KAN-197: unmodified Kubernetes templates must be refused by the deploy check."""
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "ci" / "check_placeholders.py"


def _run(d):
    return subprocess.run([sys.executable, str(CHECK), str(d)], capture_output=True, text=True)


def test_unmodified_templates_are_refused():
    r = _run(ROOT / "deploy" / "kubernetes")
    assert r.returncode == 1
    assert "secret.yaml" in r.stderr and "ingress.yaml" in r.stderr


def test_filled_in_copy_passes(tmp_path):
    d = tmp_path / "k8s"
    shutil.copytree(ROOT / "deploy" / "kubernetes", d)
    for f in d.glob("*.yaml"):
        f.write_text(re.sub(r"REPLACE_ME|yourdomain\.com|TODO:? *replace", "filled", f.read_text(), flags=re.I))
    assert _run(d).returncode == 0


def test_apply_script_runs_check_first():
    s = (ROOT / "deploy" / "kubernetes" / "apply.sh").read_text()
    assert s.index("check_placeholders.py") < s.index("kubectl apply")
