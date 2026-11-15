"""KAN-51: every alert links to a real runbook section and every section has the four parts."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/ops/RUNBOOKS.md").read_text()
COMPONENTS = ["API", "Postgres", "Redis", "Velaris", "Queue", "Approvals", "Model gateway", "Sandbox", "Preview", "Dashboard", "Ledger"]


def _anchor(h):
    return re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")


def test_every_alert_runbook_link_resolves_to_a_heading():
    anchors = {_anchor(h) for h in re.findall(r"^#{2,3} (.+)$", DOC, re.M)}
    rules = [r for g in yaml.safe_load((ROOT / "deploy/observability/alerts.yml").read_text())["groups"] for r in g["rules"]]
    for r in rules:
        link = r["annotations"]["runbook"]
        if "#" in link:
            assert link.split("#")[1] in anchors, f"{r['alert']} links to a missing section {link}"


def test_each_component_section_has_symptoms_checks_fix_escalate():
    for name in COMPONENTS:
        body = re.split(rf"^## {re.escape(name)}\s*$", DOC, flags=re.M)[1]
        body = re.split(r"^## ", body, flags=re.M)[0]
        for part in ("**Symptoms", "**Checks", "**Fix", "**Escalate"):
            assert part in body, f"{name}: missing {part}"
