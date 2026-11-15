"""Real tool results for the frontend critic: tsc, eslint (and axe-core counts from the a11y phase).

The regex scorers in dimension_scorer_frontend stay as the fallback. When a tool really ran, its
findings are added on top, per file, so a project with a type error or a known accessibility
violation scores lower than the same project judged by pattern matching alone.

tsc and eslint run through the phase sandbox (no network, run directory only), in the project's
own frontend folder; they need its node_modules, and when those are absent (or no sandbox is
available) the tool is reported as not run: never as clean.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from aether_os.core.sandbox.phase_exec import run_sync
from aether_os.core.sandbox.runner import SandboxUnavailable

logger = logging.getLogger(__name__)

_TSC_LINE = re.compile(r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+),\d+\):\s+error\s+(?P<code>TS\d+):\s+(?P<msg>.*)$")
_TOOL_TIMEOUT_S = 300


@dataclass
class FrontendToolReport:
    tsc_ran: bool = False
    eslint_ran: bool = False
    axe_violations: Optional[int] = None          # None = axe did not run
    tsc: Dict[str, List[str]] = field(default_factory=dict)       # file -> "L12 TS2322: ..."
    eslint: Dict[str, List[dict]] = field(default_factory=dict)   # file -> [{rule, severity, message, line}]
    notes: List[str] = field(default_factory=list)

    def for_file(self, file_path: str):
        """(tsc messages, eslint messages) of the file, matched by path suffix."""
        norm = file_path.replace("\\", "/")
        hit = lambda table: next((v for k, v in table.items() if norm.endswith("/" + k) or norm == k), [])  # noqa: E731
        return hit(self.tsc), hit(self.eslint)


def parse_tsc(output: str) -> Dict[str, List[str]]:
    """`src/a.tsx(10,5): error TS2322: msg` lines -> {file: ["L10 TS2322: msg"]}."""
    out: Dict[str, List[str]] = {}
    for line in output.splitlines():
        m = _TSC_LINE.match(line.strip())
        if m:
            out.setdefault(m["file"].replace("\\", "/"), []).append(f"L{m['line']} {m['code']}: {m['msg']}")
    return out


def parse_eslint(raw_json: str, root: Path) -> Dict[str, List[dict]]:
    """`eslint --format json` -> {relative file: [{rule, severity, message, line}]}."""
    out: Dict[str, List[dict]] = {}
    for entry in json.loads(raw_json):
        rel = Path(entry["filePath"]).as_posix()
        try:
            rel = Path(entry["filePath"]).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
        msgs = [{"rule": m.get("ruleId") or "", "severity": m.get("severity", 1), "message": m.get("message", ""),
                 "line": m.get("line", 0)} for m in entry.get("messages", [])]
        if msgs:
            out[rel] = msgs
    return out


def collect(frontend_dir: str, axe_violations: Optional[int] = None) -> FrontendToolReport:
    """Run tsc and eslint in the sandbox for the project's frontend folder."""
    report = FrontendToolReport(axe_violations=axe_violations)
    root = Path(frontend_dir)
    if not (root / "node_modules").is_dir():
        report.notes.append("node_modules missing: tsc and eslint did not run")
        return report
    try:
        done = run_sync(["npx", "tsc", "--noEmit", "--skipLibCheck", "--pretty", "false"], cwd=root,
                        timeout=_TOOL_TIMEOUT_S, text=True)
        report.tsc, report.tsc_ran = parse_tsc((done.stdout or "") + (done.stderr or "")), True
    except (SandboxUnavailable, subprocess.TimeoutExpired, OSError) as exc:
        report.notes.append(f"tsc did not run: {exc}")
    try:
        done = run_sync(["npx", "eslint", "--format", "json", "src"], cwd=root, timeout=_TOOL_TIMEOUT_S, text=True)
        # eslint exits 1 when it found problems and 2 when it could not run (no config, crash)
        if done.returncode in (0, 1) and (done.stdout or "").lstrip().startswith("["):
            report.eslint, report.eslint_ran = parse_eslint(done.stdout, root), True
        else:
            report.notes.append("eslint did not run (no config or crash)")
    except (SandboxUnavailable, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
        report.notes.append(f"eslint did not run: {exc}")
    return report


def apply_tools(scores: list, tsc_msgs: List[str], eslint_msgs: List[dict], axe_violations: Optional[int]) -> None:
    """Deduct tool findings from the DimensionScores of ONE file, in place."""
    from aether_os.core.quality.dimension_critic_types import PASSING_THRESHOLD
    by_name = {s.dimension: s for s in scores}

    def hit(name: str, amount: float, finding: str) -> None:
        ds = by_name.get(name)
        if ds is not None:
            ds.score = max(0.0, ds.score - amount)
            ds.findings.append(finding)
            ds.passed = ds.score >= PASSING_THRESHOLD

    if tsc_msgs:
        hit("typescript_types", min(0.6, 0.15 * len(tsc_msgs)), f"tsc: {len(tsc_msgs)} error(s), first: {tsc_msgs[0]}")
    a11y = [m for m in eslint_msgs if m["rule"].startswith("jsx-a11y/")]
    other = [m for m in eslint_msgs if not m["rule"].startswith("jsx-a11y/")]
    if a11y:
        weight = sum(0.1 if m["severity"] >= 2 else 0.05 for m in a11y)
        hit("frontend_a11y", min(0.5, weight), f"eslint jsx-a11y: {len(a11y)} finding(s), first: {a11y[0]['rule']}")
    if other:
        weight = sum(0.05 if m["severity"] >= 2 else 0.02 for m in other)
        hit("frontend_correctness", min(0.4, weight), f"eslint: {len(other)} finding(s), first: {other[0]['rule']}")
    if axe_violations:
        hit("frontend_a11y", min(0.4, 0.1 * axe_violations), f"axe-core reported {axe_violations} violation(s) on the running app")
