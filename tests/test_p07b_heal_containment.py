"""KAN-109: the self-healer must never pick (and then overwrite) a file outside the project."""
from pathlib import Path

from aether_os.phases.p07b_self_healing.task_agent import _identify_failing_file


def test_traceback_file_outside_project_is_ignored(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "victim.py"
    outside.write_text("x = 1\n")
    inside = proj / "main.py"
    inside.write_text("x = 1\n")
    out = f'File "{outside}", line 3, in f\n'
    assert _identify_failing_file(out, proj) is None
    out = f'File "{inside}", line 3, in f\nFile "{outside}", line 9, in g\n'
    assert _identify_failing_file(out, proj) == inside.resolve()


def test_pytest_marker_outside_project_is_ignored(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "victim.py"
    outside.write_text("x = 1\n")
    assert _identify_failing_file(f"ERROR collecting {outside}", proj) is None
