"""KAN-69 G7/G8: the CI workflow p08 generates had no `permissions:` block (token scope = repository default) and
its fallback Dockerfile ran the app as root."""
import asyncio
from types import SimpleNamespace

import yaml

from aether_os.phases.p08_cicd.task_agent import CICDAgent


def test_generated_ci_is_read_only_and_fallback_dockerfile_is_not_root(tmp_path):
    pi = SimpleNamespace(input_data={"project_dir": str(tmp_path), "project_name": "Demo"}, output_dir=tmp_path / "out")
    asyncio.run(CICDAgent()._run_scan(tmp_path / "src", pi))
    ci = yaml.safe_load((tmp_path / ".github/workflows/ci.yml").read_text())
    assert ci["permissions"] == {"contents": "read"}
    lines = (tmp_path / "Dockerfile").read_text().splitlines()
    assert any(ln.startswith("USER ") and ln != "USER root" for ln in lines)


def test_generated_compose_files_publish_the_api_on_loopback_only():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "phases"
    for f in ("p03_scaffolding/task_agent.py", "p08_cicd/generators.py"):
        assert '"8000:8000"' not in (root / f).read_text(), f
