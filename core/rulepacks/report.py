"""One entrypoint for all rule packs.

    report = scan_project("/path/to/generated/app", public_routes=["/health", "POST /auth/login", "/products/*"])
    report.blocking          # True when any high/critical finding remains
    report.to_json()
    repair_prompt(report.findings, "backend/app/routers/tasks.py")   # fix instruction for one file

The caller runs the repair loop (at most 3 rounds) and re-scans after each round.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from aether_os.core.rulepacks.base import BLOCKING, SEVERITIES, SEVERITY_RANK, Finding, Project
from aether_os.core.rulepacks.design_lint import lint_design
from aether_os.core.rulepacks.prodready import check_prodready
from aether_os.core.rulepacks.security_app import scan_app
from aether_os.core.rulepacks.security_py import scan_python
from aether_os.core.rulepacks.security_web import scan_web

PACKS = ("design", "security", "prodready")


@dataclass
class Report:
    root: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def by_pack(self) -> dict[str, list[Finding]]:
        return {pk: [f for f in self.findings if f.pack == pk] for pk in PACKS}

    @property
    def counts(self) -> dict[str, int]:
        return {s: sum(f.severity == s for f in self.findings) for s in SEVERITIES}

    @property
    def blocking(self) -> bool:
        return any(f.severity in BLOCKING for f in self.findings)

    def files(self) -> list[str]:
        """Files with findings, the ones with the most severe findings first."""
        worst: dict[str, int] = {}
        for f in self.findings:
            worst[f.file] = max(worst.get(f.file, 0), SEVERITY_RANK[f.severity])
        return sorted(worst, key=lambda k: (-worst[k], k))

    def to_dict(self) -> dict:
        return {
            "root": self.root, "blocking": self.blocking, "counts": self.counts,
            "counts_by_pack": {pk: {s: sum(f.severity == s for f in fs) for s in SEVERITIES} for pk, fs in self.by_pack.items()},
            "findings": {pk: [f.to_dict() for f in fs] for pk, fs in self.by_pack.items()},
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)


def _sort_key(f: Finding):
    return (-SEVERITY_RANK[f.severity], f.file, f.line, f.rule_id)


def scan_project(path: str | os.PathLike, public_routes: list[str] | None = None,
                 packs: tuple[str, ...] = PACKS) -> Report:
    """Run the selected packs over a project directory. Read-only; nothing in the project is executed.

    public_routes: paths the generator declared public ('/path', 'METHOD /path', '/prefix/*'). None uses a
    small default (health, login, register, token refresh); health and ready routes are always public.
    """
    p = Project.load(path)
    findings: list[Finding] = []
    if "design" in packs:
        findings += lint_design(p)
    if "security" in packs:
        findings += scan_python(p) + scan_app(p, public_routes) + scan_web(p)
    if "prodready" in packs:
        findings += check_prodready(p)
    unique = sorted(set(findings), key=_sort_key)  # two checks may describe the same line identically
    return Report(root=str(p.root), findings=unique)


def repair_prompt(findings: list[Finding], file: str, max_items: int = 15) -> str:
    """A concise fix instruction for one file, most severe first. '' when the file has no findings."""
    mine = sorted((f for f in findings if f.file == file), key=_sort_key)
    if not mine:
        return ""
    where = f"`{file}`" if file else "the project (files to add or change)"
    lines = [f"Fix these {len(mine)} problem(s) in {where}. Change only what each item needs and keep everything "
             "else as it is. Return the complete corrected file."]
    for i, f in enumerate(mine[:max_items], 1):
        at = f" line {f.line}" if f.line else ""
        code = f" `{f.snippet}`" if f.snippet else ""
        lines.append(f"{i}. [{f.severity}] {f.rule_id}{at}:{code} {f.message}. Fix: {f.fix_hint}.")
    if len(mine) > max_items:
        lines.append(f"({len(mine) - max_items} lower-severity item(s) omitted; they will be reported again.)")
    return "\n".join(lines)
