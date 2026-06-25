"""JavaScript and TypeScript syntax validators for DCSP.

Called by language_validators.py; never imported directly.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile

from src.validators._runner import run_cmd, tool_on_path, fmt_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

def _parse_node_stderr(stderr: str, file_path: str) -> list[str]:
    """Parse node --check stderr into canonical error strings."""
    errors: list[str] = []
    lines = stderr.splitlines()
    lineno = "0"
    for line in lines:
        m = re.match(r"[^\s]+\.js:(\d+)(?::\d+)?", line)
        if m:
            lineno = m.group(1)
            continue
        m2 = re.match(r"(SyntaxError|ReferenceError|TypeError):\s*(.+)", line)
        if m2:
            errors.append(fmt_error(file_path, lineno, m2.group(1), m2.group(2)))
    return errors


def validate_javascript(content: str, file_path: str) -> list[str]:
    if not tool_on_path("node"):
        logger.debug("node not on PATH — JavaScript validation skipped")
        return []

    errors: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd(["node", "--check", tmp])
        if result.returncode != 0:
            errors.extend(_parse_node_stderr(result.stderr or "", file_path))
    except Exception as e:
        logger.debug("node --check failed unexpectedly: %s", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------

def validate_typescript(content: str, file_path: str) -> list[str]:
    if not tool_on_path("npx"):
        logger.debug("npx not on PATH — TypeScript validation skipped")
        return []

    errors: list[str] = []
    suffix = ".tsx" if file_path.endswith(".tsx") else ".ts"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as tf:
        tf.write(content)
        tmp = tf.name
    try:
        result = run_cmd([
            "npx", "--yes", "tsc",
            "--noEmit",
            "--allowJs",
            "--checkJs",
            "--strict", "false",
            "--target", "ES2020",
            "--lib", "ES2020",
            "--skipLibCheck",
            tmp,
        ])
        output = (result.stdout or "") + (result.stderr or "")
        # tsc error format:  file.ts(LINE,COL): error TSXXXX: message
        for line in output.splitlines():
            m = re.match(r".+\((\d+),\d+\): error (TS\d+): (.+)", line)
            if m:
                errors.append(fmt_error(file_path, m.group(1), m.group(2), m.group(3)))
    except Exception as e:
        logger.debug("tsc via npx failed: %s", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return errors
