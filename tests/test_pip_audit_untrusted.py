"""KAN-101: pip-audit on a generated project's requirements must never resolve/build packages on the host."""
import subprocess
from pathlib import Path

from aether_os.core.security import code_scanner as cs


def test_only_pinned_requirements_reach_pip_audit_without_resolution(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi==0.110.0\nrequests>=2\ngit+https://evil.example/x.git\n./local\n"
                   "uvicorn[standard]==0.30.0  # c\n-r other.txt\n")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["content"] = Path(argv[argv.index("-r") + 1]).read_text()
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    cs._run_pip_audit_uncached(req)
    assert "--no-deps" in seen["argv"] and "--disable-pip" in seen["argv"]
    assert seen["content"].split() == ["fastapi==0.110.0", "uvicorn[standard]==0.30.0"]
