"""KAN-50: the alert rules parse, every rule has the fields on-call needs, and every aether_* metric they use exists in code."""
import re
from pathlib import Path

import yaml
from prometheus_client import Counter, Gauge

from aether_os.core.telemetry import metrics

ROOT = Path(__file__).resolve().parents[1]
RULES = yaml.safe_load((ROOT / "deploy/observability/alerts.yml").read_text())


def _rules():
    return [r for g in RULES["groups"] for r in g["rules"]]


def test_every_rule_has_expr_severity_summary_and_runbook():
    assert len(_rules()) >= 9
    for r in _rules():
        assert r["expr"].strip() and r["labels"]["severity"] in ("page", "ticket"), r["alert"]
        assert r["annotations"]["summary"] and r["annotations"]["runbook"].startswith("docs/ops/RUNBOOKS.md"), r["alert"]


def test_required_alert_conditions_are_present():
    names = {r["alert"] for r in _rules()}
    # service down, error spike, approval older than its reminder, budget 80%
    assert {"AetherOSApiDown", "ErrorRateSpike", "ApprovalOlderThanReminder", "OrganisationAtBudget80"} <= names


def test_metrics_used_by_alerts_are_defined_in_code():
    defined = set()
    for obj in vars(metrics).values():
        if isinstance(obj, (Counter, Gauge)):
            defined.add(obj._name)
            defined.add(obj._name + "_total")
    used = {m for r in _rules() for m in re.findall(r"\baether_[a-z_0-9]+", r["expr"])}
    assert used and not (used - defined), used - defined
