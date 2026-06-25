"""Multi-language syntax validators for DCSP.

Each validator runs via subprocess against CLI tools that are typically
pre-installed on the host.  If the required tool is absent, the validator
returns [] and logs a DEBUG message — it never raises.
No new pip dependencies are required.

JavaScript and TypeScript live in web_validators.py (imported below).
Subprocess helpers live in _runner.py.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import tempfile
from pathlib import Path

from src.validators._runner import fmt_error, run_cmd, tool_on_path
from src.validators.web_validators import validate_javascript, validate_typescript

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extension → language mapping
# ---------------------------------------------------------------------------
_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".rs": "rust",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
}


def _detect_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return _EXT_MAP.get(ext)


# ---------------------------------------------------------------------------
# Python validator
# ---------------------------------------------------------------------------
def _validate_python(content: str, file_path: str) -> list[str]:
    errors: list[str] = []

    # Pass 1: ast.parse — catches the first hard SyntaxError; return early if clean
    try:
        ast.parse(content)
        return []
    except SyntaxError as e:
        errors.append(fmt_error(file_path, e.lineno or 0, "SyntaxError", e.msg))

    # Pass 2: pyflakes for additional issues (optional dependency)
    try:
        import io as _io
        import sys as _sys
        import pyflakes.api as _pf  # type: ignore[import]

        _buf = _io.StringIO()
        _old_stderr = _sys.stderr
        _sys.stderr = _buf
        try:
            _pf.check(content, file_path)
        finally:
            _sys.stderr = _old_stderr
        for line in _buf.getvalue().splitlines():
            if line and line not in errors:
                errors.append(line)
    except Exception as e:
        logger.debug("pyflakes unavailable or failed: %s", e)

    # Pass 3: compile() — may surface a different line number
    try:
        compile(content, file_path, "exec")
    except SyntaxError as e2:
        msg = fmt_error(file_path, e2.lineno or 0, "SyntaxError", e2.msg)
        if msg not in errors:
            errors.append(msg)

    return errors


# ---------------------------------------------------------------------------
# Go validator
# ---------------------------------------------------------------------------
def _validate_go(content: str, file_path: str) -> list[str]:
    if not tool_on_path("go"):
        logger.debug("go not on PATH — Go validation skipped")
        return []

    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        go_file = os.path.join(tmp_dir, "main.go")
        with open(go_file, "w") as f:
            f.write(content)
        for cmd in (["go", "build", "./..."], ["go", "vet", "./..."]):
            try:
                result = run_cmd(cmd, cwd=tmp_dir)
                stderr = result.stderr or ""
                # ./main.go:LINE:COL: message
                for line in stderr.splitlines():
                    m = re.match(r"\./main\.go:(\d+):\d+:\s*(.+)", line)
                    if m:
                        errors.append(fmt_error(file_path, m.group(1), "GoError", m.group(2)))
            except Exception as e:
                logger.debug("go command %s failed: %s", cmd, e)
    return errors


# ---------------------------------------------------------------------------
# Ruby validator
# ---------------------------------------------------------------------------
def _validate_ruby(content: str, file_path: str) -> list[str]:
    if not tool_on_path("ruby"):
        logger.debug("ruby not on PATH — Ruby validation skipped")
        return []

    errors: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".rb", mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd(["ruby", "-c", tmp])
        stderr = result.stderr or ""
        # ruby -c: <file>:LINE: syntax error, MESSAGE
        for line in stderr.splitlines():
            m = re.match(r".+:(\d+):\s*(.+)", line)
            if m and "syntax error" in m.group(2).lower():
                errors.append(fmt_error(file_path, m.group(1), "SyntaxError", m.group(2)))
    except Exception as e:
        logger.debug("ruby -c failed: %s", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors


# ---------------------------------------------------------------------------
# Java validator
# ---------------------------------------------------------------------------
def _validate_java(content: str, file_path: str) -> list[str]:
    if not tool_on_path("javac"):
        logger.debug("javac not on PATH — Java validation skipped")
        return []

    errors: list[str] = []
    # Java requires filename == public class name
    class_name = "Main"
    m = re.search(r"\bpublic\s+class\s+(\w+)", content)
    if m:
        class_name = m.group(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        java_file = os.path.join(tmp_dir, f"{class_name}.java")
        with open(java_file, "w") as f:
            f.write(content)
        try:
            result = run_cmd(["javac", java_file])
            stderr = result.stderr or ""
            # javac stderr: FILE:LINE: error: MESSAGE
            for line in stderr.splitlines():
                m2 = re.match(r".+:(\d+): error: (.+)", line)
                if m2:
                    errors.append(fmt_error(file_path, m2.group(1), "CompileError", m2.group(2)))
        except Exception as e:
            logger.debug("javac failed: %s", e)
    return errors


# ---------------------------------------------------------------------------
# Rust validator
# ---------------------------------------------------------------------------
def _validate_rust(content: str, file_path: str) -> list[str]:
    if not tool_on_path("rustc"):
        logger.debug("rustc not on PATH — Rust validation skipped")
        return []

    errors: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd([
            "rustc", "--edition", "2021",
            "--crate-type", "lib",
            "--error-format", "short",
            tmp,
        ])
        stderr = result.stderr or ""
        # short format: FILE:LINE:COL: error[EXXXX]: MESSAGE
        for line in stderr.splitlines():
            m = re.match(r".+:(\d+):\d+: error(?:\[E\d+\])?: (.+)", line)
            if m:
                errors.append(fmt_error(file_path, m.group(1), "CompileError", m.group(2)))
    except Exception as e:
        logger.debug("rustc failed: %s", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors


# ---------------------------------------------------------------------------
# PHP validator
# ---------------------------------------------------------------------------
def _validate_php(content: str, file_path: str) -> list[str]:
    if not tool_on_path("php"):
        logger.debug("php not on PATH — PHP validation skipped")
        return []

    errors: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".php", mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd(["php", "-l", tmp])
        output = (result.stdout or "") + (result.stderr or "")
        # php -l stdout: "Parse error: syntax error, DETAILS in FILE on line LINE"
        for line in output.splitlines():
            m = re.match(r"Parse error:\s*(.+?) in .+ on line (\d+)", line)
            if m:
                errors.append(fmt_error(file_path, m.group(2), "ParseError", m.group(1)))
    except Exception as e:
        logger.debug("php -l failed: %s", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors


# ---------------------------------------------------------------------------
# C / C++ validator
# ---------------------------------------------------------------------------
def _validate_c_cpp(content: str, file_path: str, cpp: bool = False) -> list[str]:
    compiler = "g++" if cpp else "gcc"
    if not tool_on_path(compiler):
        logger.debug("%s not on PATH — %s validation skipped", compiler, "C++" if cpp else "C")
        return []

    errors: list[str] = []
    suffix = ".cpp" if cpp else ".c"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd([compiler, "-fsyntax-only", tmp])
        stderr = result.stderr or ""
        # gcc/g++ stderr: FILE:LINE:COL: error: MESSAGE
        for line in stderr.splitlines():
            m = re.match(r".+:(\d+):\d+: error: (.+)", line)
            if m:
                errors.append(fmt_error(file_path, m.group(1), "CompileError", m.group(2)))
    except Exception as e:
        logger.debug("%s -fsyntax-only failed: %s", compiler, e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------
_VALIDATORS = {
    "python": _validate_python,
    "javascript": validate_javascript,
    "typescript": validate_typescript,
    "go": _validate_go,
    "ruby": _validate_ruby,
    "java": _validate_java,
    "rust": _validate_rust,
    "php": _validate_php,
    "c": lambda c, p: _validate_c_cpp(c, p, cpp=False),
    "cpp": lambda c, p: _validate_c_cpp(c, p, cpp=True),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def collect_errors(content: str, file_path: str, language: str | None = None) -> list[str]:
    """Detect language from file_path extension if language is None.

    Run the appropriate validator(s).
    Return list of error strings in the format:
      'File "path", line N: ErrorType: message'
    Return [] if the file is clean or the validator is unavailable.
    """
    lang = language or _detect_language(file_path)
    if lang is None:
        logger.debug("No validator for file: %s", file_path)
        return []

    validator = _VALIDATORS.get(lang)
    if validator is None:
        logger.debug("No validator registered for language: %s", lang)
        return []

    try:
        return validator(content, file_path)
    except Exception as e:
        logger.warning("Validator for %s raised unexpectedly: %s", lang, e)
        return []
