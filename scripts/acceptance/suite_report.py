"""KAN-266: the suite's report: JSON plus a markdown table, per prompt and per check, with the real failure reason."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List

from acceptance.suite_checks import FAIL, PASS, SKIP, CheckResult


def verdict(checks: List[CheckResult], strict: bool = False) -> str:
    """FAIL when any check failed (or, strict, was skipped); PASS otherwise."""
    bad = {FAIL, SKIP} if strict else {FAIL}
    return FAIL if any(c.status in bad for c in checks) or not checks else PASS


def prompt_record(entry: dict, run_id: str, seconds: float, checks: List[CheckResult], strict: bool = False) -> Dict[str, Any]:
    return {"id": entry["id"], "title": entry.get("title", ""), "run_id": run_id, "seconds": round(seconds),
            "verdict": verdict(checks, strict), "checks": [asdict(c) for c in checks]}


def summary(records: List[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    n = lambda st: sum(1 for r in records for c in r["checks"] if c["status"] == st)  # noqa: E731
    return {**meta, "passed_prompts": sum(r["verdict"] == PASS for r in records), "total_prompts": len(records),
            "checks": {"pass": n(PASS), "fail": n(FAIL), "skip": n(SKIP)}, "prompts": records}


def exit_code(report: Dict[str, Any]) -> int:
    return 0 if report["total_prompts"] and report["passed_prompts"] == report["total_prompts"] else 1


def to_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str)


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")[:300]


def to_markdown(report: Dict[str, Any]) -> str:
    c = report["checks"]
    out = [f"# Acceptance suite {report.get('at', '')}", "",
           f"Target: `{report.get('target', '?')}`. Prompts passed: **{report['passed_prompts']}/{report['total_prompts']}**. "
           f"Checks: {c['pass']} pass, {c['fail']} fail, {c['skip']} skip.", "",
           "| prompt | verdict | run | passed | failed | skipped |", "|---|---|---|---|---|---|"]
    for r in report["prompts"]:
        k = [x["status"] for x in r["checks"]]
        out.append(f"| {r['id']} | {r['verdict']} | {r['run_id'] or '-'} | {k.count(PASS)} | {k.count(FAIL)} | {k.count(SKIP)} |")
    for r in report["prompts"]:
        out += ["", f"## {r['id']} - {r['title']} ({r['verdict']}, {r['seconds']} s)", "", "| check | result | reason |", "|---|---|---|"]
        out += [f"| {x['name']} | {x['status']} | {_cell(x['reason'])} |" for x in r["checks"]]
    return "\n".join(out) + "\n"
