"""
CI log ingestion and stack trace extraction for DFLE.

Parses raw CI logs from pytest, unittest, and generic Python tracebacks,
extracting structured stack traces for failure localization.
"""

from __future__ import annotations

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
        """Frame where the exception was raised: Python prints "most recent call last", so it is
        the LAST frame (the first one is only the entry point, e.g. the test runner)."""
        return self.frames[-1] if self.frames else None

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
_PYTEST_FAILED = re.compile(
    r"FAILED\s+(?P<path>[\S]+)(?:\s+[-:]\s*(?P<msg>.*))?"
)
# unittest-style: test_name ... FAIL
_UNITTEST_FAIL = re.compile(r"^(?P<name>test_\w+)\s+\.\.\.\s+FAIL", re.MULTILINE)


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
            # Continue until we hit a blank line or non-traceback content
            stripped = line.strip()
            if not stripped:
                blocks.append("\n".join(current))
                current = []
                in_traceback = False
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
    - pytest FAILED lines
    - unittest FAIL lines

    Args:
        content: Raw CI log text (stdout/stderr).

    Returns:
        ParsedLog with stack_traces, test_names, and raw content.
    """
    if not content or not isinstance(content, str):
        return ParsedLog(raw_content=content or "", errors=["Empty or invalid input"])

    errors: list[str] = []
    stack_traces: list[StackTrace] = []
    test_names: list[str] = []

    # Extract Python tracebacks
    blocks = _extract_traceback_blocks(content)
    for trace in _parse_python_traceback(blocks):
        stack_traces.append(trace)

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

    return ParsedLog(
        raw_content=content,
        stack_traces=stack_traces,
        test_names=test_names,
        errors=errors if errors else [],
    )
