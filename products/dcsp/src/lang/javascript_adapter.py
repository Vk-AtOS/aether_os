"""
JavaScript language adapter.
"""

from __future__ import annotations

import re
from typing import Optional
from src.lang.base import LanguageAdapter, LanguageFailure


class JavaScriptAdapter(LanguageAdapter):
    """Adapter for parsing JavaScript and TypeScript failures."""

    @property
    def language_name(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> list[str]:
        return [".js", ".ts", ".jsx", ".tsx"]

    def parse(self, log_output: str) -> Optional[LanguageFailure]:
        """Detect and parse JavaScript failures."""
        try:
            # Node.js stack trace pattern: at function (file:line:col)
            # or: at file:line:col
            stack_match = re.search(r"at (?:(?P<func>[^\s(]+) )?\(?(?P<file>[^:)]+):(?P<line>\d+):(?P<col>\d+)\)?", log_output)
            
            is_node = False
            if stack_match:
                failing_file = stack_match.group("file")
                if any(failing_file.endswith(ext) for ext in self.file_extensions):
                    is_node = True

            is_jest = "FAIL " in log_output or "● " in log_output
            is_error = re.search(r"(?:TypeError|ReferenceError|Error):", log_output)

            if not (is_node or is_jest or is_error):
                return None

            # Extract error type and message
            error_match = re.search(r"(?P<type>\w+Error|Error): (?P<msg>.*)", log_output)
            error_type = error_match.group("type") if error_match else "Error"
            error_message = error_match.group("msg").splitlines()[0] if error_match else "Unknown error"

            failing_file = "unknown"
            line_number = 0
            failing_function = "unknown"

            if stack_match:
                failing_file = stack_match.group("file")
                line_number = int(stack_match.group("line"))
                failing_function = stack_match.group("func") or "<anonymous>"
            elif is_jest:
                # Jest specific: FAIL src/path/to/test.js
                jest_file_match = re.search(r"FAIL (?P<file>\S+)", log_output)
                if jest_file_match:
                    failing_file = jest_file_match.group("file")

            return LanguageFailure(
                language=self.language_name,
                error_type=error_type,
                error_message=error_message,
                failing_file=failing_file,
                failing_function=failing_function,
                line_number=line_number,
                raw_traceback=log_output # Simplified for now
            )
        except Exception:
            return None
