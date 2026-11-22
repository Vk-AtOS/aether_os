"""Undefined names in model-written business logic, found statically (ruff F821); the code is never run here.

Production acceptance run 19 (22 Nov 2026): the model's workflow_engine.py referenced `_apply_task_status_change`
without defining it. It parsed, so p04b wrote it; importing the app then failed with NameError and s06 ran no test.
A module with undefined names is now refused and p04b keeps its deterministic fallback, as it already does for a
SyntaxError.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import List

logger = logging.getLogger(__name__)


def undefined_names(code: str, filename: str) -> List[str]:
    """`filename: undefined name 'x' at line n` for each F821 finding; [] when clean or ruff is unavailable."""
    ruff = shutil.which("ruff")
    if ruff is None:
        logger.debug("p04b: ruff not on PATH, undefined-name check skipped for %s", filename)
        return []
    try:
        res = subprocess.run([ruff, "check", "--select", "F821", "--output-format", "json", "--no-cache",
                              "--stdin-filename", filename, "-"], input=code, capture_output=True, text=True,
                             timeout=30)
        findings = json.loads(res.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.warning("p04b: undefined-name check failed for %s: %s", filename, exc)
        return []
    return [f"{filename}: {f.get('message', 'undefined name')} at line {f.get('location', {}).get('row', '?')}"
            for f in findings if f.get("code") == "F821"]
