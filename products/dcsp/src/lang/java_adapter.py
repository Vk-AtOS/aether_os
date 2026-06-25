"""
Java language adapter.
"""

from __future__ import annotations

import re
from typing import Optional
from src.lang.base import LanguageAdapter, LanguageFailure


class JavaAdapter(LanguageAdapter):
    """Adapter for parsing Java failures."""

    @property
    def language_name(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> list[str]:
        return [".java"]

    def parse(self, log_output: str) -> Optional[LanguageFailure]:
        """Detect and parse Java failures."""
        has_exception = "Exception in thread" in log_output or "Caused by:" in log_output
        has_junit = "FAILURES!!!" in log_output or "Tests run:" in log_output
        has_stack_frame = re.search(r"at [\w\.]+\.[\w\$]+\([\w\.]+\.java:\d+\)", log_output)

        if not (has_exception or has_junit or has_stack_frame):
            return None

        try:
            # Extract error type (e.g. java.lang.NullPointerException)
            error_match = re.search(r"(?P<type>[\w\.]+(?:Exception|Error|Throwable|AssertionError))", log_output)
            error_type = error_match.group("type") if error_match else "JavaException"
            
            # Message is usually after the type on the same line
            msg_match = re.search(fr"{re.escape(error_type)}:? (?P<msg>.*)", log_output)
            error_message = msg_match.group("msg").splitlines()[0] if msg_match else "Java error"

            # Find all stack frames
            # Stack frame pattern: at com.example.Class.method(File.java:42)
            frame_pattern = r"at (?P<pkg_class>[\w\.]+)\.(?P<method>[\w\$]+)\((?P<file>[\w\.]+\.java):(?P<line>\d+)\)"
            frames = list(re.finditer(frame_pattern, log_output))
            
            failing_file = "unknown"
            line_number = 0
            failing_function = "unknown"

            if frames:
                # Try to find the first frame that is NOT a library (junit, java, sun)
                target_frame = frames[0]
                for frame in frames:
                    pkg = frame.group("pkg_class")
                    if not any(pkg.startswith(lib) for lib in ["org.junit", "java.", "sun.", "com.sun."]):
                        target_frame = frame
                        break
                
                failing_file = target_frame.group("file")
                line_number = int(target_frame.group("line"))
                failing_function = f"{target_frame.group('pkg_class')}.{target_frame.group('method')}"

            return LanguageFailure(
                language=self.language_name,
                error_type=error_type,
                error_message=error_message,
                failing_file=failing_file,
                failing_function=failing_function,
                line_number=line_number,
                raw_traceback=log_output # Simplified
            )
        except Exception:
            return None
