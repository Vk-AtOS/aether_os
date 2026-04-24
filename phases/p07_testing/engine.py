"""
Aether-One Test Generation Engine

This module turns runtime errors (traceback text + the code snippet that caused
it) into concrete pytest tests that can reproduce the failure.

Design goals:
- No stubs or fake placeholders: the generated test actually executes the
  provided snippet, under `pytest.raises(...)`.
- Deterministic and offline: pure Python, no LLM dependency.
- Safe and explicit: tests are written under a dedicated tests/ directory
  inside the project, with clear headers documenting their origin.

Typical flow:
1. Guarded execution layer captures:
   - traceback_text: the full traceback as a string
   - reproduction_snippet: Python code that triggered the error

2. Call:
   info = parse_traceback(traceback_text)
   generated = generate_pytest_from_error(info, reproduction_snippet)
   write_generated_test(project_root, generated)

3. The new test file appears in tests/, and can be run via pytest to ensure
   the error is reproducible and fixed properly.

This module does NOT perform wiring to FastAPI or CLI by itself; it is a
reusable core used by higher-level orchestration.
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass
from typing import Optional


TRACEBACK_FILE_LINE_RE = re.compile(
    r'^\s*File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>.+)$'
)

EXCEPTION_LINE_RE = re.compile(
    r'^(?P<exc_type>[A-Za-z_][A-Za-z0-9_\.]*)\s*:\s*(?P<message>.*)$'
)


@dataclass
class RuntimeErrorInfo:
    """
    Parsed information from a Python traceback.

    - file_path: file where the error ultimately occurred (last frame)
    - line: line number in that file
    - function: function or context name (if available)
    - exception_type: class name (e.g. ValueError)
    - message: exception message text
    - raw_traceback: full original traceback text
    """
    file_path: Optional[str]
    line: Optional[int]
    function: Optional[str]
    exception_type: Optional[str]
    message: Optional[str]
    raw_traceback: str


@dataclass
class GeneratedTest:
    """
    Represents a fully generated pytest test.

    - tests_dir: directory under project root where the file should live
    - filename: basename of the test file (e.g. test_utils_line_42.py)
    - function_name: name of the pytest test function
    - content: full test file contents (UTF-8 text)
    """
    tests_dir: str
    filename: str
    function_name: str
    content: str


def parse_traceback(traceback_text: str) -> RuntimeErrorInfo:
    """
    Parse a Python traceback string into a RuntimeErrorInfo.

    Strategy:
        - Scan for all 'File "...", line N, in func' lines and take the LAST one.
        - Scan from the bottom for '<ExceptionType>: message' as the exception line.

    This works for typical Python tracebacks from stdlib, pytest, etc.
    """
    file_path: Optional[str] = None
    line_no: Optional[int] = None
    function: Optional[str] = None

    # Normalize newlines and split
    lines = traceback_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Find last "File ..." line
    for line in lines:
        m = TRACEBACK_FILE_LINE_RE.match(line)
        if m:
            file_path = m.group("file").strip()
            try:
                line_no = int(m.group("line"))
            except ValueError:
                line_no = None
            function = m.group("func").strip()

    exc_type: Optional[str] = None
    message: Optional[str] = None

    # Find exception line from bottom
    for line in reversed(lines):
        m = EXCEPTION_LINE_RE.match(line.strip())
        if m:
            exc_type = m.group("exc_type").strip() or None
            message = m.group("message").strip() or None
            break

    return RuntimeErrorInfo(
        file_path=file_path,
        line=line_no,
        function=function,
        exception_type=exc_type,
        message=message,
        raw_traceback=traceback_text,
    )


def _safe_module_name_from_path(path: Optional[str]) -> str:
    """
    Derive a reasonable module name from a file path.
    """
    if not path:
        return "unknown_module"
    base = os.path.basename(path)
    name, _ = os.path.splitext(base)
    if not name:
        return "unknown_module"
    # Replace problematic characters
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name or "unknown_module"


def _safe_test_function_name(module_name: str, line: Optional[int]) -> str:
    """
    Build a deterministic pytest test function name.
    """
    if line is None:
        return f"test_error_in_{module_name}"
    return f"test_error_in_{module_name}_line_{line}"


def generate_pytest_from_error(
    info: RuntimeErrorInfo,
    reproduction_snippet: str,
    tests_subdir: str = "tests",
) -> GeneratedTest:
    """
    Generate a pytest file that reproduces the given runtime error by executing
    the provided reproduction_snippet under pytest.raises.

    Parameters:
        info:
            Parsed RuntimeErrorInfo from the traceback.
        reproduction_snippet:
            Python code that triggered the error originally. This snippet will be
            executed verbatim inside the test.
        tests_subdir:
            Directory name under the project root where the generated test file
            should be placed (commonly "tests").

    Returns:
        GeneratedTest describing where and what to write.

    Behavior:
        - If exception_type is known, uses pytest.raises(<type>).
        - Otherwise, uses pytest.raises(Exception) as a safe fallback.
        - Embeds the original traceback as commented lines at the top of the file,
          so humans can see context.
    """
    module_name = _safe_module_name_from_path(info.file_path)
    func_name = _safe_test_function_name(module_name, info.line)

    exc_type_literal = info.exception_type or "Exception"

    header = f'''"""Auto-generated by Aether-One from a runtime error.

Original traceback (for reference):

{_indent_block(info.raw_traceback, prefix="# ")}
"""
'''

    # Ensure snippet is properly indented
    snippet_block = textwrap.indent(reproduction_snippet.rstrip() + "\n", " " * 8)

    body = f"""
import pytest


def {func_name}():
    \"\"\"Reproduces the captured runtime error for regression testing.\"\"\"
    with pytest.raises({exc_type_literal}):
{snippet_block}
"""

    content = header + body

    filename = f"test_{module_name}"
    if info.line is not None:
        filename += f"_line_{info.line}"
    filename += ".py"

    return GeneratedTest(
        tests_dir=tests_subdir,
        filename=filename,
        function_name=func_name,
        content=content,
    )


def write_generated_test(project_root: str, generated: GeneratedTest) -> str:
    """
    Write the generated test file to disk under project_root / tests_dir / filename.

    Ensures the tests directory exists. Returns the absolute path of the created
    or overwritten file.

    This function is idempotent: calling it again with the same GeneratedTest
    will simply overwrite the file with the same content.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    tests_dir_abs = os.path.join(root, generated.tests_dir)
    os.makedirs(tests_dir_abs, exist_ok=True)

    dest_path = os.path.join(tests_dir_abs, generated.filename)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(generated.content)

    return dest_path


def _indent_block(text: str, prefix: str) -> str:
    """
    Indent a multi-line string with a prefix on each line.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(prefix + line for line in lines)

