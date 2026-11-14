"""KAN-99/KAN-100: generated monitoring stack loads its alert rules and has no fixed Grafana password."""
import asyncio
from types import SimpleNamespace

import yaml

from aether_os.phases.p09_observability import task_agent


def _generate(tmp_path):
    pi = SimpleNamespace(input_data={"project_name": "Demo"})
    asyncio.run(task_agent.run(pi, [], tmp_path))
    return tmp_path / "monitoring"


def test_prometheus_loads_the_alert_rules(tmp_path):
    mon = _generate(tmp_path)
    cfg = yaml.safe_load((mon / "prometheus.yml").read_text())
    assert cfg["rule_files"] == ["/etc/prometheus/prometheus_alerts.yml"]
    assert (mon / "prometheus_alerts.yml").exists()
    compose = yaml.safe_load((mon / "docker-compose.monitoring.yml").read_text())
    assert any("prometheus_alerts.yml:/etc/prometheus/prometheus_alerts.yml" in v
               for v in compose["services"]["prometheus"]["volumes"])


def test_grafana_password_is_not_a_literal(tmp_path):
    compose = (_generate(tmp_path) / "docker-compose.monitoring.yml").read_text()
    pw = yaml.safe_load(compose)["services"]["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"]
    assert pw != "admin" and pw.startswith("${GRAFANA_ADMIN_PASSWORD:?")
