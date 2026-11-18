"""
Tiered test execution for DSEE Phase 3.

Runs tests in three tiers:
Tier 1: Specific failing test.
Tier 2: Module-related tests.
Tier 3: Full test suite (asynchronous).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from typing import Optional

from aether_os.core.sandbox.phase_exec import run_sync
from aether_os.core.sandbox.runner import SandboxUnavailable

logger = logging.getLogger(__name__)

_TEST_TIMEOUT_S = 600


@dataclass
class TieredTestRunResult:
    """Result of a tiered test run."""

    tier: int
    passed: bool
    output: str
    pending: bool = False


class TieredTestRunner:
    """Handles tiered test execution using pytest."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self._last_tier3_result: Optional[TieredTestRunResult] = None
        self._tier3_thread: Optional[threading.Thread] = None

    def _run_pytest(self, args: list[str]) -> tuple[bool, str]:
        """Run pytest on the repo through the sandbox and return (passed, output).

        The repo content comes from a webhook, i.e. it is untrusted code: it must never run
        on the platform host. No sandbox available means the tests did not run (fail closed).
        """
        try:
            result = run_sync(["python3", "-m", "pytest", *args], cwd=self.root_dir,
                              timeout=_TEST_TIMEOUT_S, text=True)
            return result.returncode == 0, result.stdout + result.stderr
        except SandboxUnavailable as e:
            logger.error("p08_cicd dsee test_runner: tests not run, %s", e)
            return False, str(e)
        except subprocess.TimeoutExpired:
            return False, f"pytest timed out after {_TEST_TIMEOUT_S}s"
        except Exception as e:
            logger.warning("p08_cicd dsee test_runner: pytest execution failed: %s", e)
            return False, str(e)

    def run_tier1(self, test_name: str) -> TieredTestRunResult:
        """
        Tier 1: Run specific failing test by name.
        Args:
            test_name: Fully qualified test name (e.g., 'tests/foo.py::test_bar')
        """
        passed, output = self._run_pytest([test_name])
        return TieredTestRunResult(tier=1, passed=passed, output=output)

    def run_tier2(self, target_file: str) -> TieredTestRunResult:
        """
        Tier 2: Run tests related to the target file (same module name).
        Args:
            target_file: Path to the source file (e.g., 'src/api/auth.py')
        """
        # Simple heuristic: find test file with matching name
        # e.g., src/api/auth.py -> tests/**/test_auth.py
        p = Path(target_file)
        stem = p.stem
        if stem.startswith("test_"):
            test_pattern = f"tests/**/{stem}.py"
        else:
            test_pattern = f"tests/**/test_{stem}.py"

        # Try to find matching test files
        test_files = list(self.root_dir.glob(test_pattern))
        if not test_files:
            return TieredTestRunResult(tier=2, passed=True, output="No related tests found, skipping.")

        args = [str(tf.relative_to(self.root_dir)) for tf in test_files]
        passed, output = self._run_pytest(args)
        return TieredTestRunResult(tier=2, passed=passed, output=output)

    def run_tier3(self) -> TieredTestRunResult:
        """
        Tier 3: Run full test suite (asynchronous).
        Returns immediately with pending=True.
        """
        if self._tier3_thread and self._tier3_thread.is_alive():
            return TieredTestRunResult(tier=3, passed=False, output="Tier 3 run already in progress.", pending=True)

        def _async_run():
            passed, output = self._run_pytest([])
            self._last_tier3_result = TieredTestRunResult(tier=3, passed=passed, output=output, pending=False)

        self._tier3_thread = threading.Thread(target=_async_run, daemon=True)
        self._tier3_thread.start()

        return TieredTestRunResult(tier=3, passed=False, output="Full suite run started in background.", pending=True)

    def poll_tier3(self) -> Optional[TieredTestRunResult]:
        """Check if background Tier 3 run is complete."""
        return self._last_tier3_result
