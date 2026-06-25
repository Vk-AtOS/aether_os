"""Tests for src.dsee.test_runner."""

import time
import os
import tempfile
import subprocess
from pathlib import Path

import pytest

from src.dsee.test_runner import TieredTestRunner, TieredTestRunResult


@pytest.fixture
def test_env():
    """Create a temporary project structure for testing the runner."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Create a dummy source file
        (root / "src").mkdir()
        (root / "src" / "__init__.py").touch()
        (root / "src" / "math_util.py").write_text("def add(a, b): return a + b\n")

        # Create dummy test files
        (root / "tests").mkdir()
        (root / "tests" / "__init__.py").touch()
        (root / "tests" / "test_math_util.py").write_text(
            "from src.math_util import add\n"
            "def test_add(): assert add(1, 1) == 2\n"
            "def test_fail(): assert False\n"
        )
        (root / "tests" / "test_other.py").write_text("def test_pass(): pass\n")

        # Set PYTHONPATH so subprocess pytest can find 'src'
        os.environ["PYTHONPATH"] = str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")

        yield root


def test_tier1_specific_test(test_env):
    runner = TieredTestRunner(test_env)
    # Run the passing test specifically
    res = runner.run_tier1(f"tests/test_math_util.py::test_add")
    assert res.tier == 1
    if not res.passed:
        print(f"TIER 1 OUTPUT: {res.output}")
    assert res.passed is True
    assert "test_math_util.py" in res.output

    # Run the failing test specifically
    res = runner.run_tier1(f"tests/test_math_util.py::test_fail")
    assert res.tier == 1
    assert res.passed is False


def test_tier2_module_related(test_env):
    runner = TieredTestRunner(test_env)
    # Run tests related to src/math_util.py -> should run tests/test_math_util.py
    res = runner.run_tier2("src/math_util.py")
    assert res.tier == 2
    # It contains a failing test, so it should fail
    assert res.passed is False
    assert "test_math_util.py" in res.output


def test_tier3_async_full_suite(test_env):
    runner = TieredTestRunner(test_env)
    # Start Tier 3
    res = runner.run_tier3()
    assert res.tier == 3
    assert res.pending is True
    assert "background" in res.output

    # Poll until finished (with timeout)
    timeout = 10
    start = time.time()
    final_res = None
    while time.time() - start < timeout:
        final_res = runner.poll_tier3()
        if final_res:
            break
        time.sleep(0.5)

    assert final_res is not None
    assert final_res.tier == 3
    assert final_res.pending is False
    # The whole suite has failing tests
    assert final_res.passed is False
    assert "test_math_util.py" in final_res.output
    assert "test_other.py" in final_res.output


def test_tier2_no_tests_found(test_env):
    runner = TieredTestRunner(test_env)
    res = runner.run_tier2("src/non_existent.py")
    assert res.tier == 2
    assert res.passed is True
    assert "No related tests found" in res.output
