"""One way to run and read bandit on GENERATED code (KAN-69 SC-04).

Two ways a scan used to pass without scanning: bandit auto-loads a `.bandit` file from the tree it scans (the
generated project can `skips` every test or `exclude` itself), and a crash printed nothing, which was read as
"no findings". `--ini` pins the configuration to an empty file of ours, and `parse` raises on empty output.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

_EMPTY_INI = str(Path(__file__).with_name("bandit_empty.ini"))


class BanditScanError(RuntimeError):
    """bandit produced no usable report: the scan did not happen."""


def bandit_args(target: Union[str, Path], *extra: str) -> List[str]:
    """Arguments after `bandit` / `python -m bandit`: recursive, JSON, our configuration, then `extra`."""
    return ["--ini", _EMPTY_INI, "-r", "-f", "json", *extra, str(target)]


def parse(stdout: Union[str, bytes, None]) -> Dict[str, Any]:
    text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else (stdout or "")
    if not text.strip():
        raise BanditScanError("bandit printed no report")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise BanditScanError(f"bandit report is not JSON: {e}") from None
    if not isinstance(data, dict) or "results" not in data:
        raise BanditScanError("bandit report has no results section")
    return data
