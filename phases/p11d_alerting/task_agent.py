"""P11d Task Agent — generate alertmanager + alert rules."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_dir = Path(data.get("project_dir", str(output_dir)))
    mon_dir = output_dir / "monitoring"
    mon_dir.mkdir(exist_ok=True)

    alert_rules = """groups:
  - name: aetheros_alerts
    rules:
      - alert: APIDown
        expr: up{job="app"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "API is down"
          description: "No scrape from app for > 1 minute"

      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error rate > 1%"
          description: "{{ $value | humanizePercentage }} of requests are errors"

      - alert: HighP95Latency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency > 2s"
          description: "P95 latency is {{ $value | humanizeDuration }}"

      - alert: HighDiskUsage
        expr: (1 - (node_filesystem_free_bytes / node_filesystem_size_bytes)) > 0.80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage > 80%"
          description: "Disk is {{ $value | humanizePercentage }} full"

      - alert: CriticalMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) > 0.90
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Memory usage > 90%"
          description: "Memory is {{ $value | humanizePercentage }} used"

      - alert: TestAlert
        expr: vector(1)
        for: 0m
        labels:
          severity: info
          test: "true"
        annotations:
          summary: "AetherOS test alert — fires and resolves immediately"
"""
    rules_path = mon_dir / "alert_rules.yml"
    rules_path.write_text(alert_rules)

    alertmanager_yml = """global:
  resolve_timeout: 5m
  slack_api_url: ${SLACK_WEBHOOK_URL}

route:
  group_by: [alertname, severity]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: default
  routes:
    - match:
        severity: critical
      receiver: critical
    - match:
        severity: warning
      receiver: warning

receivers:
  - name: default
    slack_configs:
      - channel: "#alerts"
        title: "{{ .GroupLabels.alertname }}"
        text: "{{ range .Alerts }}{{ .Annotations.description }}{{ end }}"

  - name: critical
    slack_configs:
      - channel: "#ops-critical"
        send_resolved: true
    email_configs:
      - to: ${ALERT_EMAIL}
        from: alerts@aetheros.ai
        smarthost: smtp.gmail.com:587
        auth_username: ${ALERT_EMAIL}
        auth_password: ${GMAIL_APP_PASSWORD}

  - name: warning
    slack_configs:
      - channel: "#alerts"
        send_resolved: true

inhibit_rules:
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: [alertname]
"""
    am_path = mon_dir / "alertmanager.yml"
    am_path.write_text(alertmanager_yml)

    # Check validity
    import yaml
    issues = []
    try:
        yaml.safe_load(alert_rules)
        yaml.safe_load(alertmanager_yml)
    except Exception as e:
        issues.append(f"YAML parse error: {e}")

    rule_count = alert_rules.count("- alert:")
    if rule_count < 5:
        issues.append(f"Only {rule_count} alert rules (need >= 5)")

    return TaskResult(
        output_path=str(mon_dir),
        confidence=0.95 if not issues else 0.4,
        metadata={"rule_count": rule_count, "alertmanager_ok": am_path.exists()},
        issues=issues,
        success=len(issues) == 0,
    )
