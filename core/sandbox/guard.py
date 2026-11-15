from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import List
from aether_os.core.errors import SandboxViolation

logger = logging.getLogger(__name__)

FORBIDDEN_EXEC_PATTERNS = [
    (r"os\.kill\s*\(", "os.kill"),
    (r"os\.system\s*\(", "os.system"),
    (r"subprocess\.", "subprocess"),
    (r"__import__\s*\(", "__import__"),
    (r"exec\s*\(", "exec"),
    (r"shell\s*=\s*True", "shell=True"),
]

SCAN_PATTERNS = [
    (r"\beval\s*\(", "eval"),
    (r"os\.system\s*\(", "os.system"),
    (r"__import__\s*\(", "__import__"),
    (r"subprocess\.call\s*\(", "subprocess.call"),
    (r"shell\s*=\s*True", "shell=True"),
    (r"exec\s*\(", "exec"),
]


class Sandbox:
    def __init__(self, root_path: Path, allow_network: bool = False):
        self.root_path = root_path.resolve()
        self.allow_network = allow_network

    def is_path_allowed(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root_path)
            return True
        except ValueError:
            return False

    def validate_path(self, path: Path) -> None:
        if not self.is_path_allowed(path):
            raise SandboxViolation(
                f"Path outside sandbox: {path}"
            )

    def execute(self, code: str) -> None:
        for pattern, label in FORBIDDEN_EXEC_PATTERNS:
            if re.search(pattern, code):
                raise SandboxViolation(
                    f"Forbidden operation in code: {label}"
                )
    
    def run_pytest(self, code: str, tests: str) -> str:
        """Run pytest on the given code and tests in a temporary directory."""
        import subprocess
        import tempfile
        
        # Validation
        self.execute(code)
        self.execute(tests)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            code_file = tmp_path / "solution.py"
            test_file = tmp_path / "test_solution.py"
            
            code_file.write_text(code)
            test_file.write_text(f"from solution import *\n\n{tests}")
            
            try:
                # Use current python to run pytest
                result = subprocess.run(
                    ["python", "-m", "pytest", str(test_file)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=tmpdir
                )
                return result.stdout + result.stderr
            except subprocess.TimeoutExpired:
                return "Error: Test execution timed out (30s)"
            except Exception as e:
                logger.warning("SandboxGuard.run_tests failed: %s", e)
                return f"Error running tests: {str(e)}"

    def scan_code(self, code: str) -> List[str]:
        issues = []
        for pattern, label in SCAN_PATTERNS:
            if re.search(pattern, code):
                issues.append(f"Dangerous pattern: {label}")
        return issues

    def safe_write(self, path: Path, content: str) -> None:
        # Always enforce root_path boundary for writes
        try:
            path.resolve().relative_to(self.root_path)
        except ValueError:
            raise SandboxViolation(
                f"Write blocked — outside sandbox: {path}"
            ) from None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def safe_read(self, path: Path) -> str:
        self.validate_path(path)
        return path.read_text(encoding="utf-8", errors="ignore")
