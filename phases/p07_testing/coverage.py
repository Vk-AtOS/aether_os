"""
Aether-One Coverage Assistant

This module provides an enterprise-grade, offline coverage analyzer that:

- Runs the project's test suite under `coverage run`.
- Generates a JSON coverage report via `coverage json`.
- Parses the results into a structured Python dictionary.
- Produces a prioritized list of files with lowest coverage, so other
  modules (temporal risk, policy, planners) can decide what to focus on.

It does not depend on FastAPI or the orchestrator; it is a pure Python core
that can be called from endpoints, agents, or the CLI.

Requirements:
    - The `coverage` Python package must be installed in the environment.
      If it is missing, this module fails gracefully and returns a clear
      error message instead of placeholders.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FileCoverage:
    path: str
    percent_covered: float
    covered_lines: int
    missing_lines: int
    num_statements: int
    executed_lines: List[int]
    missing_line_numbers: List[int]


@dataclass
class CoverageSummary:
    total_percent_covered: float
    total_covered_lines: int
    total_missing_lines: int
    total_num_statements: int


@dataclass
class CoverageResult:
    ok: bool
    project_path: str
    command: str
    coverage_file: Optional[str]
    coverage_json_path: Optional[str]
    tests_ok: bool
    tests_exit_code: int
    tests_stdout: str
    tests_stderr: str
    coverage_stdout: str
    coverage_stderr: str
    summary: Optional[CoverageSummary]
    files: List[FileCoverage]
    prioritized_files: List[FileCoverage]
    warning: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a JSON-serializable dict.
        """
        data = asdict(self)
        # dataclasses inside dataclasses have been flattened by asdict
        return data


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_coverage_json(path: str) -> Tuple[Optional[CoverageSummary], List[FileCoverage]]:
    """
    Parse coverage JSON file produced by `coverage json`.

    Coverage JSON schema (simplified):

        {
          "meta": {...},
          "files": {
            "/path/to/file.py": {
              "executed_lines": [1, 2, 3],
              "missing_lines": [5, 6],
              "summary": {
                "covered_lines": 10,
                "num_statements": 20,
                "percent_covered": 50.0,
                "missing_lines": 10
              }
            },
            ...
          },
          "totals": {
            "covered_lines": ...,
            "num_statements": ...,
            "percent_covered": ...,
            "missing_lines": ...
          }
        }
    """
    if not os.path.exists(path):
        return None, []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, []

    files_data = data.get("files") or {}
    totals_data = data.get("totals") or {}

    files: List[FileCoverage] = []
    for file_path, info in files_data.items():
        summary = info.get("summary") or {}
        files.append(
            FileCoverage(
                path=file_path,
                percent_covered=_safe_float(summary.get("percent_covered", 0.0)),
                covered_lines=_safe_int(summary.get("covered_lines", 0)),
                missing_lines=_safe_int(summary.get("missing_lines", 0)),
                num_statements=_safe_int(summary.get("num_statements", 0)),
                executed_lines=list(info.get("executed_lines") or []),
                missing_line_numbers=list(info.get("missing_lines") or []),
            )
        )

    summary = CoverageSummary(
        total_percent_covered=_safe_float(totals_data.get("percent_covered", 0.0)),
        total_covered_lines=_safe_int(totals_data.get("covered_lines", 0)),
        total_missing_lines=_safe_int(totals_data.get("missing_lines", 0)),
        total_num_statements=_safe_int(totals_data.get("num_statements", 0)),
    )

    return summary, files


def run_coverage(
    project_path: str,
    test_command: str = "pytest",
    coverage_file_name: str = ".coverage.aetherone",
    coverage_json_name: str = ".coverage.aetherone.json",
    max_prioritized: int = 20,
) -> CoverageResult:
    """
    Run tests under coverage in the given project_path and return a CoverageResult.

    Parameters:
        project_path:
            Root of the project whose tests should be run.

        test_command:
            The module (and arguments) to run via `coverage run -m`.
            For example:
                "pytest"
                "pytest -q"
                "unittest discover"

        coverage_file_name:
            File name for the coverage data file (COVERAGE_FILE).

        coverage_json_name:
            File name for the JSON report produced by `coverage json`.

        max_prioritized:
            Number of low-coverage files to highlight in prioritized_files.

    Behavior:
        - Validates that project_path is a directory.
        - Sets COVERAGE_FILE to a project-local file.
        - Executes `coverage run -m <test_command>` in that directory.
        - Then executes `coverage json -o <coverage_json_name>`.
        - Parses the JSON and returns a structured CoverageResult.

    Failure Handling:
        - If `coverage` CLI is missing, returns ok=False with a clear error.
        - If tests fail, tests_ok will be False but coverage can still be ok.
        - If JSON parsing fails, ok=False with error message.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))

    if not os.path.isdir(project_abs):
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=None,
            coverage_json_path=None,
            tests_ok=False,
            tests_exit_code=-1,
            tests_stdout="",
            tests_stderr="",
            coverage_stdout="",
            coverage_stderr="",
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=f"project_path is not a directory: {project_abs}",
        )

    env = os.environ.copy()
    # Ensure project is on PYTHONPATH so tests can import it.
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = project_abs + (os.pathsep + existing_pp if existing_pp else "")

    coverage_file = os.path.join(project_abs, coverage_file_name)
    coverage_json_path = os.path.join(project_abs, coverage_json_name)
    env["COVERAGE_FILE"] = coverage_file

    # Build `coverage run -m <test_command>` command.
    module_and_args = shlex.split(test_command)
    if not module_and_args:
        module_and_args = ["pytest"]

    run_cmd = ["coverage", "run", "-m"] + module_and_args

    tests_stdout = ""
    tests_stderr = ""
    tests_exit_code = -1
    tests_ok = False
    coverage_stdout = ""
    coverage_stderr = ""
    warning: Optional[str] = None
    error: Optional[str] = None

    start_time = time.time()
    try:
        run_proc = subprocess.run(
            run_cmd,
            cwd=project_abs,
            env=env,
            capture_output=True,
            text=True,
        )
        tests_stdout = run_proc.stdout
        tests_stderr = run_proc.stderr
        tests_exit_code = run_proc.returncode
        tests_ok = (run_proc.returncode == 0)
    except FileNotFoundError as e:
        # coverage CLI is not installed
        error = (
            "coverage CLI not found. Please install it in your environment, e.g.:\n"
            "    pip install coverage\n\n"
            f"Underlying error: {e}"
        )
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=None,
            coverage_json_path=None,
            tests_ok=False,
            tests_exit_code=-1,
            tests_stdout="",
            tests_stderr="",
            coverage_stdout="",
            coverage_stderr="",
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=error,
        )
    except Exception as e:
        error = f"Unexpected error while running tests under coverage: {e}"
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=None,
            coverage_json_path=None,
            tests_ok=False,
            tests_exit_code=-1,
            tests_stdout="",
            tests_stderr="",
            coverage_stdout="",
            coverage_stderr="",
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=error,
        )

    # Even if tests failed, we still attempt to generate coverage JSON.
    json_cmd = ["coverage", "json", "-o", coverage_json_path]
    try:
        json_proc = subprocess.run(
            json_cmd,
            cwd=project_abs,
            env=env,
            capture_output=True,
            text=True,
        )
        coverage_stdout = json_proc.stdout
        coverage_stderr = json_proc.stderr
        if json_proc.returncode != 0:
            error = (
                "coverage json command failed. "
                f"Return code: {json_proc.returncode}. "
                f"Stderr: {coverage_stderr.strip()}"
            )
            return CoverageResult(
                ok=False,
                project_path=project_abs,
                command=test_command,
                coverage_file=coverage_file,
                coverage_json_path=coverage_json_path,
                tests_ok=tests_ok,
                tests_exit_code=tests_exit_code,
                tests_stdout=tests_stdout,
                tests_stderr=tests_stderr,
                coverage_stdout=coverage_stdout,
                coverage_stderr=coverage_stderr,
                summary=None,
                files=[],
                prioritized_files=[],
                warning=None,
                error=error,
            )
    except FileNotFoundError as e:
        # Extremely unlikely if coverage run worked, but handle anyway.
        error = (
            "coverage CLI not found while generating JSON report. "
            "Please ensure the `coverage` package is installed.\n"
            f"Underlying error: {e}"
        )
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=coverage_file,
            coverage_json_path=coverage_json_path,
            tests_ok=tests_ok,
            tests_exit_code=tests_exit_code,
            tests_stdout=tests_stdout,
            tests_stderr=tests_stderr,
            coverage_stdout=coverage_stdout,
            coverage_stderr=coverage_stderr,
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=error,
        )
    except Exception as e:
        error = f"Unexpected error while generating coverage JSON: {e}"
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=coverage_file,
            coverage_json_path=coverage_json_path,
            tests_ok=tests_ok,
            tests_exit_code=tests_exit_code,
            tests_stdout=tests_stdout,
            tests_stderr=tests_stderr,
            coverage_stdout=coverage_stdout,
            coverage_stderr=coverage_stderr,
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=error,
        )

    # Parse JSON
    summary, files = _parse_coverage_json(coverage_json_path)
    if summary is None:
        error = (
            "Failed to parse coverage JSON report. "
            f"Expected file at: {coverage_json_path}"
        )
        return CoverageResult(
            ok=False,
            project_path=project_abs,
            command=test_command,
            coverage_file=coverage_file,
            coverage_json_path=coverage_json_path,
            tests_ok=tests_ok,
            tests_exit_code=tests_exit_code,
            tests_stdout=tests_stdout,
            tests_stderr=tests_stderr,
            coverage_stdout=coverage_stdout,
            coverage_stderr=coverage_stderr,
            summary=None,
            files=[],
            prioritized_files=[],
            warning=None,
            error=error,
        )

    # Prioritize files with lowest coverage; break ties by most statements.
    prioritized = sorted(
        files,
        key=lambda f: (f.percent_covered, -f.num_statements),
    )[: max_prioritized]

    # Warn if tests failed but coverage is still computed.
    if not tests_ok and tests_exit_code != 0:
        warning = (
            "Tests did not pass (non-zero exit code), but coverage data was "
            "successfully generated. Investigate failing tests before relying "
            "on coverage numbers for sign-off."
        )

    elapsed = time.time() - start_time
    if warning is None:
        warning = f"Coverage run completed in {elapsed:.2f}s."
    else:
        warning = f"{warning} [Coverage run completed in {elapsed:.2f}s.]"

    return CoverageResult(
        ok=True,
        project_path=project_abs,
        command=test_command,
        coverage_file=coverage_file,
        coverage_json_path=coverage_json_path,
        tests_ok=tests_ok,
        tests_exit_code=tests_exit_code,
        tests_stdout=tests_stdout,
        tests_stderr=tests_stderr,
        coverage_stdout=coverage_stdout,
        coverage_stderr=coverage_stderr,
        summary=summary,
        files=files,
        prioritized_files=prioritized,
        warning=warning,
        error=None,
    )

