"""Tests for src.dsee.boundary."""

from src.dsee.boundary import BoundaryCheckResult, check_boundary


def _diff(filepath: str, *hunk_lines: str) -> str:
    return (
        f"diff --git a/{filepath} b/{filepath}\n"
        "index 123..456 789\n"
        f"--- a/{filepath}\n"
        f"+++ b/{filepath}\n"
        + "".join(hunk_lines)
    )


def test_valid_single_file_patch() -> None:
    diff = _diff("src/foo.py", "@@ -5,3 +5,4 @@\n", " def bar():\n", "     x = 1\n", "+    y = 2\n", "     return x\n")
    r = check_boundary(diff, "src/foo.py")
    assert r.passed
    assert r.violations == []


def test_multi_file_rejected() -> None:
    diff = _diff("a.py", "+x\n") + _diff("b.py", "+y\n")
    r = check_boundary(diff, "a.py")
    assert not r.passed
    assert any("single file" in v.lower() for v in r.violations)


def test_max_lines_exceeded() -> None:
    diff = _diff("x.py", "@@ -1,0 +1,41 @@\n") + "\n".join("+line" for _ in range(41))
    r = check_boundary(diff, "x.py")
    assert not r.passed
    assert any("40" in v for v in r.violations)


def test_forbidden_manifest() -> None:
    diff = _diff("requirements.txt", "+foo==1.0\n")
    r = check_boundary(diff, "requirements.txt")
    assert not r.passed
    assert any("requirements" in v or "excluded" in v for v in r.violations)


def test_forbidden_ci() -> None:
    diff = _diff(".github/workflows/ci.yml", "+ step\n")
    r = check_boundary(diff, ".github/workflows/ci.yml")
    assert not r.passed


def test_forbidden_infra() -> None:
    diff = _diff("Dockerfile", "+RUN apt-get update\n")
    r = check_boundary(diff, "Dockerfile")
    assert not r.passed


def test_target_mismatch() -> None:
    diff = _diff("src/foo.py", "+x\n")
    r = check_boundary(diff, "src/other.py")
    assert not r.passed
    assert any("target" in v.lower() or "modifies" in v.lower() for v in r.violations)


def test_empty_patch() -> None:
    r = check_boundary("", "src/foo.py")
    assert not r.passed
    assert any("no file" in v.lower() for v in r.violations)


def test_unified_diff_no_git_header() -> None:
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1,1 +1,2 @@\n"
        " def bar():\n"
        "+    pass\n"
    )
    r = check_boundary(diff, "src/foo.py")
    assert r.passed
    assert r.violations == []


def test_boundary_result_fields() -> None:
    r = BoundaryCheckResult(passed=True, violations=[])
    assert r.passed is True
    assert r.violations == []
