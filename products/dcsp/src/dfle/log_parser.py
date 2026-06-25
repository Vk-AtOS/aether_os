"""
CI log ingestion and stack trace extraction for DFLE.

Parses raw CI logs from pytest, unittest, and generic Python tracebacks,
extracting structured stack traces for failure localization.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterator


@dataclass(frozen=True)
class StackFrame:
    """A single frame in a stack trace."""

    filename: str
    line: int
    function: str
    code_snippet: str | None = None


@dataclass
class StackTrace:
    """An extracted stack trace from a CI log."""

    exception_type: str
    exception_message: str
    frames: list[StackFrame] = field(default_factory=list)
    raw_text: str = ""

    @property
    def top_frame(self) -> StackFrame | None:
        """First frame (entry point / failure location)."""
        return self.frames[0] if self.frames else None

    @property
    def failure_site(self) -> str | None:
        """Human-readable failure location for fingerprinting."""
        if frame := self.top_frame:
            return f"{frame.filename}:{frame.line}:{frame.function}"
        return None


@dataclass
class LogSourceMetadata:
    """Optional source metadata for CI log provenance."""

    repo_name: str | None = None
    branch: str | None = None
    ci_job_name: str | None = None


@dataclass
class ParsedLog:
    """Result of CI log parsing."""

    raw_content: str
    stack_traces: list[StackTrace] = field(default_factory=list)
    test_names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source: LogSourceMetadata | None = None
    # Populated by parse_log
    detected_language: str = "unknown"
    error_type: str = "Unknown"
    fingerprint: str = ""

    @property
    def primary_trace(self) -> StackTrace | None:
        """Most relevant trace for localization (first/last failure)."""
        return self.stack_traces[0] if self.stack_traces else None


# --- Python traceback patterns ---

_TRACEBACK_HEADER = re.compile(
    r"Traceback \(most recent call last\):",
    re.MULTILINE,
)
_PYTHON_FRAME = re.compile(
    r'\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?'
)
_PYTHON_EXCEPTION = re.compile(
    r"^(?P<etype>\w+(?:\.\w+)*): (?P<msg>.*)$"
)
# pytest-style: FAILED path/to/test.py::test_name - AssertionError: message
# Must use MULTILINE so ^ anchors work correctly; named groups used by _extract_pytest_failures.
_PYTEST_FAILED = re.compile(
    r"^FAILED\s+(?P<path>[\S]+)(?:\s+[-:]\s*(?P<msg>.*))?"
    , re.MULTILINE
)
# unittest-style: test_name ... FAIL
_UNITTEST_FAIL = re.compile(r"^(?P<name>test_\w+)\s+\.\.\.\s+FAIL", re.MULTILINE)

# --- Python language / error detection patterns (for logs without full traceback header) ---

# Bare Python exception lines — matches both line-start ("ImportError: ...") and
# mid-line pytest style ("FAILED tests/foo.py::test_bar - ImportError: ...")
_BARE_PYTHON_EXCEPTION = re.compile(
    r"(?:^|\s-\s)(?P<etype>"
    r"ModuleNotFoundError|ImportError|AttributeError|TypeError|ValueError"
    r"|KeyError|RuntimeError|Exception|SyntaxError|NameError|IndexError"
    r"|ZeroDivisionError|FileNotFoundError|PermissionError|OSError"
    r"|ConnectionError|TimeoutError|StopIteration|AssertionError"
    r")\s*:\s*(?P<msg>.*)$",
    re.MULTILINE,
)

# `raise SomeError(...)` lines
_RAISE_LINE = re.compile(r"^\s*raise\s+\w+", re.MULTILINE)

# Python File frame without traceback header
_PYTHON_FILE_FRAME = re.compile(r'File "[^"]+\.py", line \d+')

# JavaScript/Node stack frame  (to distinguish from Python)
_JS_FRAME = re.compile(r"at \w[\w.]+ \([^)]+:\d+:\d+\)")

# Java stack frame
_JAVA_FRAME = re.compile(r"at [\w.]+\([\w.]+\.java:\d+\)")

# Error-type → canonical error_type mapping
_ERROR_TYPE_MAP = {
    "ModuleNotFoundError": "ImportError",
    "ImportError": "ImportError",
    "AttributeError": "AttributeError",
    "TypeError": "TypeError",
    "SyntaxError": "SyntaxError",
    "KeyError": "KeyError",
    "ValueError": "ValueError",
    "NameError": "NameError",
    "IndexError": "IndexError",
    "ZeroDivisionError": "RuntimeError",
    "RuntimeError": "RuntimeError",
    "Exception": "RuntimeError",
    "AssertionError": "AssertionError",
    "FileNotFoundError": "IOError",
    "PermissionError": "IOError",
    "OSError": "IOError",
    "ConnectionError": "NetworkError",
    "TimeoutError": "NetworkError",
    "StopIteration": "RuntimeError",
}

# Build/compile-failure keywords
_BUILD_ERROR_PATTERNS = re.compile(
    r"BUILD FAILED|compilation failed|error: cannot find symbol"
    r"|undefined reference|linker error|npm ERR!|yarn error",
    re.IGNORECASE | re.MULTILINE,
)


def _classify_error_type(raw_etype: str) -> str:
    """Map a raw exception name to a canonical DCSP error type."""
    return _ERROR_TYPE_MAP.get(raw_etype, "RuntimeError")


def _detect_language(content: str) -> str:
    """
    Detect programming language from log content.

    Python is checked first because Python logs often include phrases like
    'Error' that could also match generic patterns.  We require at least
    one Python-specific signal (traceback header, .py file frame, or a bare
    Python exception name) before declaring 'python'.
    """
    has_traceback_header = bool(_TRACEBACK_HEADER.search(content))
    has_py_frame = bool(_PYTHON_FILE_FRAME.search(content))
    has_bare_python_exc = bool(_BARE_PYTHON_EXCEPTION.search(content))
    has_raise = bool(_RAISE_LINE.search(content))
    has_pytest_failed = bool(_PYTEST_FAILED.search(content))

    if has_traceback_header or has_py_frame or has_bare_python_exc or has_raise or has_pytest_failed:
        return "python"

    if bool(_JAVA_FRAME.search(content)):
        return "java"

    if bool(_JS_FRAME.search(content)):
        return "javascript"

    return "unknown"


def _build_fingerprint(language: str, error_type: str, file_pattern: str) -> str:
    """Stable 16-char fingerprint from (language, error_type, file_path_pattern)."""
    payload = f"{language}|{error_type}|{file_pattern}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parse_python_traceback(blocks: list[str]) -> Iterator[StackTrace]:
    """Parse Python traceback blocks into StackTrace objects."""
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        frames: list[StackFrame] = []
        exception_type = "Exception"
        exception_message = ""

        i = 0
        while i < len(lines):
            line = lines[i]

            if _PYTHON_FRAME.match(line.strip()):
                m = _PYTHON_FRAME.match(line.strip())
                if m:
                    path = m.group("path")
                    line_num = int(m.group("line"))
                    func = m.group("func") or "<module>"
                    snippet = lines[i + 1].strip() if i + 1 < len(lines) else None
                    if snippet and not snippet.startswith("File "):
                        frames.append(
                            StackFrame(
                                filename=path,
                                line=line_num,
                                function=func,
                                code_snippet=snippet,
                            )
                        )
                        i += 2
                        continue
                    else:
                        frames.append(
                            StackFrame(
                                filename=path,
                                line=line_num,
                                function=func,
                                code_snippet=None,
                            )
                        )
            elif m := _PYTHON_EXCEPTION.match(line.strip()):
                exception_type = m.group("etype")
                exception_message = m.group("msg").strip()
                break
            i += 1

        if frames or exception_type or exception_message:
            yield StackTrace(
                exception_type=exception_type,
                exception_message=exception_message,
                frames=frames,
                raw_text=block.strip(),
            )


def _extract_traceback_blocks(content: str) -> list[str]:
    """Split log content into traceback blocks."""
    blocks: list[str] = []
    current: list[str] = []
    in_traceback = False

    for line in content.splitlines():
        if _TRACEBACK_HEADER.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
            in_traceback = True
        elif in_traceback:
            # Continue until we hit the exception type line or clearly non-traceback content.
            # Blank lines are kept (SyntaxError tracebacks have a blank line before the
            # exception type line — closing on blank would lose the exception type).
            stripped = line.strip()
            if not stripped:
                current.append(line)  # keep blank line; exception type may follow
            elif stripped.startswith("File ") or stripped.startswith("During "):
                current.append(line)
            elif _PYTHON_EXCEPTION.match(stripped):
                current.append(line)
                blocks.append("\n".join(current))
                current = []
                in_traceback = False
            else:
                current.append(line)
        else:
            if current and not line.strip().startswith(" "):
                blocks.append("\n".join(current))
                current = []
            in_traceback = False

    if current:
        blocks.append("\n".join(current))

    return blocks


def _extract_pytest_failures(content: str) -> list[tuple[str, str]]:
    """Extract FAILED lines from pytest output. Returns (path_or_test_id, msg)."""
    results: list[tuple[str, str]] = []
    for m in _PYTEST_FAILED.finditer(content):
        path = m.group("path").strip()
        msg_group = m.group("msg")
        msg = msg_group.strip() if msg_group else ""
        results.append((path, msg))
    return results


def _extract_unittest_failures(content: str) -> list[str]:
    """Extract failed test names from unittest output."""
    return [m.group("name") for m in _UNITTEST_FAIL.finditer(content)]


def parse_log(content: str) -> ParsedLog:
    """
    Ingest CI log content and extract stack traces and test metadata.

    Supports:
    - Python tracebacks (Traceback (most recent call last): ...)
    - Bare Python exceptions (ModuleNotFoundError, ImportError, …) without header
    - pytest FAILED lines
    - unittest FAIL lines

    Args:
        content: Raw CI log text (stdout/stderr).

    Returns:
        ParsedLog with stack_traces, test_names, detected_language, error_type,
        fingerprint, and raw content.
    """
    if not content or not isinstance(content, str):
        return ParsedLog(raw_content=content or "", errors=["Empty or invalid input"])

    errors: list[str] = []
    stack_traces: list[StackTrace] = []
    test_names: list[str] = []

    # Check for build/compile failures first
    is_build_error = bool(_BUILD_ERROR_PATTERNS.search(content))

    # Extract full Python tracebacks (with "Traceback (most recent call last):" header)
    blocks = _extract_traceback_blocks(content)
    for trace in _parse_python_traceback(blocks):
        stack_traces.append(trace)

    # If no full traceback found, check for bare Python exception lines.
    # A bare exception appears in logs like:
    #   ModuleNotFoundError: No module named 'requests'
    # without the Traceback header that _extract_traceback_blocks requires.
    if not stack_traces:
        for m in _BARE_PYTHON_EXCEPTION.finditer(content):
            raw_etype = m.group("etype")
            msg = m.group("msg").strip()
            # Try to find a nearby File frame on surrounding lines
            frames: list[StackFrame] = []
            for fm in _PYTHON_FRAME.finditer(content):
                path = fm.group("path")
                line_num = int(fm.group("line"))
                func = fm.group("func") or "<module>"
                frames.append(StackFrame(filename=path, line=line_num, function=func))

            stack_traces.append(
                StackTrace(
                    exception_type=raw_etype,
                    exception_message=msg,
                    frames=frames,
                    raw_text=m.group(0),
                )
            )
            # Only capture the first bare exception to avoid duplicates
            break

    # Extract pytest failures (for test names / context)
    for path, msg in _extract_pytest_failures(content):
        test_names.append(path)
        if not stack_traces and path:
            # Extract file from path (e.g. tests/foo.py::test_bar -> tests/foo.py)
            filename = path.split("::")[0] if "::" in path else path
            # Minimal trace from pytest line when no full traceback
            stack_traces.append(
                StackTrace(
                    exception_type="AssertionError",
                    exception_message=msg,
                    frames=[StackFrame(filename=filename, line=0, function="")],
                    raw_text=msg,
                )
            )

    # Extract unittest failures
    for name in _extract_unittest_failures(content):
        if name not in test_names:
            test_names.append(name)

    # -----------------------------------------------------------------------
    # Derive language, error_type, and fingerprint
    # -----------------------------------------------------------------------
    detected_language = _detect_language(content)

    # error_type from the first stack trace (or build/compile fallback)
    raw_etype = ""
    if stack_traces:
        raw_etype = stack_traces[0].exception_type or ""

    if is_build_error and not raw_etype:
        error_type = "BuildError"
    elif raw_etype:
        error_type = _classify_error_type(raw_etype)
    else:
        error_type = "Unknown"

    # fingerprint: hash of (language, error_type, top file path)
    top_file = ""
    if stack_traces and stack_traces[0].frames:
        top_file = stack_traces[0].frames[0].filename
    fingerprint = _build_fingerprint(detected_language, error_type, top_file)

    return ParsedLog(
        raw_content=content,
        stack_traces=stack_traces,
        test_names=test_names,
        errors=errors if errors else [],
        detected_language=detected_language,
        error_type=error_type,
        fingerprint=fingerprint,
    )
