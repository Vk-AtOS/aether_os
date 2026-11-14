"""KAN-109: s03 gate understands Go/TypeScript output; s09 returns a string output_path."""
import asyncio
from pathlib import Path

from aether_os.phases.base import TaskResult
from aether_os.stages.s03_backend.helpers import validate_backend_output
from aether_os.stages.s09_devops import supervisor as s09


def test_go_backend_passes(tmp_path):
    (tmp_path / "main.go").write_text("package main")
    (tmp_path / "go.mod").write_text("module x")
    assert validate_backend_output(str(tmp_path)) == []


def test_typescript_backend_passes(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("")
    (tmp_path / "package.json").write_text("{}")
    assert validate_backend_output(str(tmp_path)) == []


def test_incomplete_go_and_python_still_fail(tmp_path):
    (tmp_path / "main.go").write_text("package main")
    assert validate_backend_output(str(tmp_path)) == ["go.mod"]
    assert len(validate_backend_output(str(tmp_path / "nope"))) == 5


def test_s09_finders_accept_no_output_dir(tmp_path):
    assert s09._find_dockerfile(None, None) == ""
    (tmp_path / "Dockerfile").write_text("FROM x")
    assert s09._find_dockerfile(None, tmp_path).endswith("Dockerfile")


def test_s09_task_result_output_path_is_a_string():
    # PhaseResult(output_path: str) rejects Path objects; the supervisor must hand it a str
    from aether_os.orchestrator.messages import PhaseResult
    src = Path(s09.__file__).read_text()
    assert 'output_path=str(p11_out or p08_out or "")' in src
    PhaseResult(run_id="r", phase="p", status="passed", output_path=str(Path("/x")))
