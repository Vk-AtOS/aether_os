"""
Python language adapter.
"""

from __future__ import annotations

import re
from typing import Optional
from aether_os.phases.p08_cicd.lang.base import LanguageAdapter, LanguageFailure


class PythonAdapter(LanguageAdapter):
    """Adapter for parsing Python failures."""

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py"]

    def parse(self, log_output: str) -> Optional[LanguageFailure]:
        """Detect and parse Python tracebacks."""
        if "Traceback (most recent call last)" not in log_output:
            return None

        try:
            # Find the start of the last traceback
            start_index = log_output.rfind("Traceback (most recent call last):")
            if start_index == -1:
                return None
            
            traceback_text = log_output[start_index:]
            lines = traceback_text.strip().splitlines()
            
            # Extract the actual traceback block (up to the next non-indented line after the first few)
            actual_lines = [lines[0]]
            for line in lines[1:]:
                actual_lines.append(line)
                # If we have a line that doesn't start with space AND it's after some "File" lines, 
                # it's likely the error message (the end of traceback)
                if not line.startswith(" ") and len(actual_lines) > 2:
                    break
            
            lines = actual_lines
            last_traceback = "\n".join(lines)
            
            # Error type and message are usually on the last line
            last_line = lines[-1]
            error_match = re.match(r"^(?P<type>[\w\.]+): (?P<msg>.*)$", last_line)
            error_type = error_match.group("type") if error_match else "Exception"
            error_message = error_match.group("msg") if error_match else last_line

            # Find the last "File" line
            failing_file = "unknown"
            line_number = 0
            failing_function = "unknown"

            for line in reversed(lines):
                file_match = re.search(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?', line)
                if file_match:
                    failing_file = file_match.group("file")
                    line_number = int(file_match.group("line"))
                    failing_function = file_match.group("func") or "<module>"
                    break

            return LanguageFailure(
                language=self.language_name,
                error_type=error_type,
                error_message=error_message,
                failing_file=failing_file,
                failing_function=failing_function,
                line_number=line_number,
                raw_traceback=last_traceback
            )
        except Exception:
            return None
