"""KAN-99: critical and high block delivery by default, medium/low warn; AETHER_BLOCKING_SEVERITIES overrides."""
import json

from aether_os.core.policy.blocking_severities import blocking_severities, blocks
from aether_os.phases.base import TaskResult
from aether_os.phases.p06_review_security import gate
from aether_os.stages.s05_quality.gate_functions import blocking_findings


def _result(tmp_path, severity):
    p = tmp_path / "sec.json"
    p.write_text(json.dumps({"security": {"findings": [{"severity": severity}]}}))
    return TaskResult(output_path=str(p), confidence=1.0, success=True)


def test_default_blocks_critical_and_high_only(monkeypatch):
    monkeypatch.delenv("AETHER_BLOCKING_SEVERITIES", raising=False)
    assert blocking_severities() == ("critical", "high")
    assert blocks("HIGH") and blocks("critical") and not blocks("medium") and not blocks("low")


def test_env_override_and_invalid_value_falls_back(monkeypatch):
    monkeypatch.setenv("AETHER_BLOCKING_SEVERITIES", "critical")
    assert not blocks("high")
    monkeypatch.setenv("AETHER_BLOCKING_SEVERITIES", "nonsense")
    assert blocks("high")


def test_p06_gate_blocks_high_and_warns_on_medium(tmp_path, monkeypatch):
    monkeypatch.delenv("AETHER_BLOCKING_SEVERITIES", raising=False)
    assert not gate.validate(_result(tmp_path, "high")).passed
    assert not gate.validate(_result(tmp_path, "critical")).passed
    out = gate.validate(_result(tmp_path, "medium"))
    assert out.passed and any("MEDIUM" in i for i in out.issues)
    monkeypatch.setenv("AETHER_BLOCKING_SEVERITIES", "critical")
    assert gate.validate(_result(tmp_path, "high")).passed


def test_s05_blocking_findings_follow_the_setting(monkeypatch):
    items = [{"issue_type": "security_finding", "severity": s, "description": s} for s in ("critical", "high", "medium")]
    monkeypatch.delenv("AETHER_BLOCKING_SEVERITIES", raising=False)
    assert blocking_findings(items) == ["critical", "high"]
