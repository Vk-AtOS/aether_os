"""KAN-109: the self-healer must never pick (and then overwrite) a file outside the project."""

from aether_os.phases.p07b_self_healing.task_agent import _identify_failing_file


def test_traceback_file_outside_project_is_ignored(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "victim.py"
    outside.write_text("x = 1\n")
    (proj / "src").mkdir()
    inside = proj / "src" / "main.py"
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


def test_vendored_dependencies_and_tests_are_never_the_failing_file(tmp_path):
    # Run da281716: the last traceback frame was the run's dependency dir; all 5 heal attempts targeted it and the
    # whole-file fallback rewrote sqlalchemy/testing/warnings.py.
    proj = tmp_path / "proj"
    dep = proj / ".deps-b9c6987285ca0cdc" / "sqlalchemy" / "testing" / "warnings.py"
    dep.parent.mkdir(parents=True)
    dep.write_text("x = 1\n")
    test = proj / "src" / "tests" / "test_main.py"
    test.parent.mkdir(parents=True)
    test.write_text("x = 1\n")
    schemas = proj / "src" / "schemas.py"
    schemas.write_text("x = 1\n")
    out = f'File "{schemas}", line 1, in <module>\nFile "{test}", line 2, in t\nFile "{dep}", line 9, in warn\n'
    assert _identify_failing_file(out, proj) == schemas.resolve()
    assert _identify_failing_file(f'File "{dep}", line 9, in warn\n', proj) is None


def test_whole_file_rewrite_refuses_a_file_outside_src(tmp_path, monkeypatch):
    import asyncio

    from aether_os.phases.p07b_self_healing import patch_repair

    dep = tmp_path / ".deps-x" / "lib.py"
    dep.parent.mkdir(parents=True)
    dep.write_text("x = 1\n")
    rewrites = []

    async def no_patches(prompt, tag):
        return []

    async def rewrite(*a):
        rewrites.append(a)
        return "x = 2\n"

    monkeypatch.setattr(patch_repair, "request_patches", no_patches)
    changed = asyncio.run(patch_repair.heal_file(dep, tmp_path, tmp_path / "test_x.py", "boom", None, "", 1, rewrite))
    assert changed is False and rewrites == [] and dep.read_text() == "x = 1\n"
