"""P11d Alerting — generate Alertmanager config, Prometheus alert rules, and runbooks."""
from __future__ import annotations
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    alerting_dir = output_dir / "alerting"
    runbook_dir = alerting_dir / "alert_runbooks"
    alerting_dir.mkdir(parents=True, exist_ok=True)
    runbook_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name = data.get("project_name", "app")

    # ── Alertmanager config ───────────────────────────────────────────────────
    alertmanager_yml = textwrap.dedent("""\
        global:
          resolve_timeout: 5m
          slack_api_url: "${SLACK_WEBHOOK_URL}"

        route:
          receiver: default
          group_by: [alertname, severity]
          group_wait: 30s
          group_interval: 5m
          repeat_interval: 4h
          routes:
            - match:
                severity: critical
              receiver: pagerduty
              repeat_interval: 1h
            - match:
                severity: warning
              receiver: slack

        receivers:
          - name: default
            slack_configs:
              - channel: "#alerts"
                title: "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"
                text: "{{ range .Alerts }}{{ .Annotations.description }}{{ end }}"

          - name: slack
            slack_configs:
              - channel: "#alerts"
                send_resolved: true
                title: "[{{ .Status | toUpper }}{{ if eq .Status \"firing\" }}:{{ .Alerts.Firing | len }}{{ end }}] {{ .CommonLabels.alertname }}"
                text: >-
                  {{ range .Alerts }}
                  *Alert:* {{ .Annotations.summary }}
                  *Description:* {{ .Annotations.description }}
                  *Severity:* {{ .Labels.severity }}
                  {{ end }}

          - name: pagerduty
            pagerduty_configs:
              - service_key: "${PAGERDUTY_SERVICE_KEY}"
                send_resolved: true

        inhibit_rules:
          - source_match:
              severity: critical
            target_match:
              severity: warning
            equal: [alertname]
    """)
    (alerting_dir / "alertmanager.yml").write_text(alertmanager_yml)

    # ── Prometheus alert rules ────────────────────────────────────────────────
    alert_rules_yml = textwrap.dedent(f"""\
        groups:
          - name: {project_name}_api_alerts
            interval: 30s
            rules:
              - alert: HighErrorRate
                expr: |
                  (
                    sum(rate(http_requests_total{{status=~"5.."}}[5m]))
                    /
                    sum(rate(http_requests_total[5m]))
                  ) > 0.05
                for: 2m
                labels:
                  severity: critical
                annotations:
                  summary: "High error rate on {project_name}"
                  description: "Error rate is {{{{ $value | humanizePercentage }}}} (threshold: 5%)"
                  runbook: "alert_runbooks/HighErrorRate.md"

              - alert: HighLatencyP95
                expr: |
                  histogram_quantile(0.95,
                    sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler)
                  ) > 2.0
                for: 3m
                labels:
                  severity: warning
                annotations:
                  summary: "High P95 latency on {project_name}"
                  description: "P95 latency is {{{{ $value }}}}s for handler {{{{ $labels.handler }}}} (threshold: 2s)"
                  runbook: "alert_runbooks/HighLatency.md"

              - alert: DatabaseConnectionPoolExhausted
                expr: |
                  db_pool_available_connections < 2
                for: 1m
                labels:
                  severity: critical
                annotations:
                  summary: "Database connection pool exhausted"
                  description: "Only {{{{ $value }}}} connections available in the pool"
                  runbook: "alert_runbooks/DBConnectionPoolExhausted.md"

              - alert: ServiceDown
                expr: up == 0
                for: 1m
                labels:
                  severity: critical
                annotations:
                  summary: "Service {project_name} is down"
                  description: "The service has been unreachable for 1 minute"
                  runbook: "alert_runbooks/ServiceDown.md"

              - alert: HighMemoryUsage
                expr: process_resident_memory_bytes > 500 * 1024 * 1024
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "High memory usage on {project_name}"
                  description: "Memory usage is {{{{ $value | humanize }}}}B (threshold: 500MB)"

              - alert: HighCPUUsage
                expr: |
                  rate(process_cpu_seconds_total[5m]) > 0.8
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "High CPU usage on {project_name}"
                  description: "CPU usage is {{{{ $value | humanizePercentage }}}}"
    """)
    (alerting_dir / "alert_rules.yml").write_text(alert_rules_yml)

    # ── Runbooks ──────────────────────────────────────────────────────────────
    runbooks = {
        "HighErrorRate.md": textwrap.dedent(f"""\
            # Runbook: High Error Rate

            **Alert:** 5xx error rate > 5% for 2 minutes

            ## Immediate Actions

            1. Check recent deployments: `git log --oneline -10`
            2. Check application logs: `docker logs {project_name.lower().replace(' ', '-')} --tail 200`
            3. Check `/health` endpoint is responding: `curl http://localhost:8000/health`

            ## Investigation

            ```bash
            # Check error distribution by endpoint
            curl http://localhost:8000/metrics | grep http_requests_total | grep 5

            # Check database connectivity
            curl http://localhost:8000/health/db

            # Review recent errors
            grep -i "error\\|exception\\|traceback" /var/log/app.log | tail -50
            ```

            ## Resolution

            - **Deployment issue**: Roll back with `docker pull <prev-image> && docker-compose up -d`
            - **Database issue**: See DBConnectionPoolExhausted runbook
            - **Dependency down**: Check external service status pages

            ## Escalation

            If not resolved in 15 minutes, escalate to on-call engineer.
        """),
        "HighLatency.md": textwrap.dedent("""\
            # Runbook: High P95 Latency

            **Alert:** P95 response time > 2 seconds for 3 minutes

            ## Immediate Actions

            1. Identify slow endpoints from metrics: `curl http://localhost:8000/metrics | grep duration`
            2. Check database query times
            3. Check external dependency latencies

            ## Investigation

            ```bash
            # Check database slow queries (PostgreSQL)
            psql $DATABASE_URL -c "SELECT query, mean_exec_time, calls FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"

            # Check if rate limiting is throttling
            curl -I http://localhost:8000/api/endpoint

            # Profile with py-spy (if installed)
            py-spy top --pid $(pgrep uvicorn)
            ```

            ## Resolution

            - **N+1 queries**: Add `select_related`/`joinedload` to ORM queries
            - **Missing index**: `CREATE INDEX CONCURRENTLY ON table_name(column);`
            - **External API slow**: Add timeout + circuit breaker
            - **CPU-bound**: Scale horizontally or optimize algorithm

            ## Escalation

            Page backend team if P95 > 5s or if affecting > 20% of requests.
        """),
        "DBConnectionPoolExhausted.md": textwrap.dedent(f"""\
            # Runbook: Database Connection Pool Exhausted

            **Alert:** Fewer than 2 connections available in DB pool

            ## Immediate Actions

            1. Check current connections: `SELECT count(*) FROM pg_stat_activity;`
            2. Check for long-running queries: `SELECT pid, query, query_start FROM pg_stat_activity WHERE state = 'active' ORDER BY query_start;`
            3. Kill blocking queries if safe: `SELECT pg_terminate_backend(pid);`

            ## Investigation

            ```bash
            # Connection pool status from app metrics
            curl http://localhost:8000/metrics | grep db_pool

            # Check pool config in environment
            echo $DATABASE_POOL_SIZE  # default: 10

            # PostgreSQL max connections
            psql $DATABASE_URL -c "SHOW max_connections;"
            ```

            ## Resolution

            - **Connection leak**: Check code for unclosed sessions (look for `session.close()`)
            - **Pool too small**: Increase `DATABASE_POOL_SIZE` env var (default 10)
            - **Long transactions**: Find and optimize queries holding connections
            - **Emergency**: Restart the app to reset pool: `docker restart {project_name.lower().replace(' ', '-')}`

            ## Escalation

            If connection count keeps growing after restart, escalate — likely a code bug.
        """),
        "ServiceDown.md": textwrap.dedent(f"""\
            # Runbook: Service Down

            **Alert:** `/health` endpoint unreachable for 1 minute

            ## Immediate Actions

            1. Check container status: `docker ps | grep {project_name.lower().replace(' ', '-')}`
            2. Check container logs: `docker logs {project_name.lower().replace(' ', '-')} --tail 100`
            3. Attempt to restart: `docker restart {project_name.lower().replace(' ', '-')}`

            ## Investigation

            ```bash
            # Check if port is bound
            ss -tlnp | grep 8000

            # Check disk space (common cause of crashes)
            df -h

            # Check memory
            free -m

            # Review kernel OOM logs
            dmesg | grep -i "killed process"
            ```

            ## Resolution

            - **OOM kill**: Increase container memory limit or optimize memory usage
            - **Disk full**: Clean logs/tmp: `docker system prune -f`
            - **Crash loop**: Review logs for unhandled exception at startup
            - **Port conflict**: Check what's on port 8000: `lsof -i :8000`

            ## Escalation

            If service doesn't recover after 2 restarts, escalate immediately.
        """),
    }
    for filename, content in runbooks.items():
        (runbook_dir / filename).write_text(content)

    # ── Alert test script ─────────────────────────────────────────────────────
    test_script = textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"
        Simulate alert conditions for testing Alertmanager routing.
        Run against a local Alertmanager: python alert_test_script.py
        \"\"\"
        import json
        import os
        import time
        import urllib.request
        import urllib.error

        ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "http://localhost:9093")


        def fire_alert(alertname: str, severity: str, summary: str, description: str) -> bool:
            payload = [{{
                "labels": {{
                    "alertname": alertname,
                    "severity": severity,
                    "job": "{project_name}",
                }},
                "annotations": {{
                    "summary": summary,
                    "description": description,
                }},
                "startsAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }}]
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{{ALERTMANAGER_URL}}/api/v1/alerts",
                data=body,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    print(f"✓ Fired {{alertname}} ({{severity}}): {{resp.status}}")
                    return True
            except urllib.error.URLError as e:
                print(f"✗ Could not reach Alertmanager at {{ALERTMANAGER_URL}}: {{e}}")
                return False


        def resolve_alert(alertname: str) -> bool:
            payload = [{{
                "labels": {{
                    "alertname": alertname,
                    "severity": "warning",
                    "job": "{project_name}",
                }},
                "endsAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }}]
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{{ALERTMANAGER_URL}}/api/v1/alerts",
                data=body,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    print(f"✓ Resolved {{alertname}}: {{resp.status}}")
                    return True
            except urllib.error.URLError as e:
                print(f"✗ Could not reach Alertmanager: {{e}}")
                return False


        if __name__ == "__main__":
            print(f"Testing alerts against {{ALERTMANAGER_URL}}\\n")

            fire_alert("HighErrorRate", "critical", "High error rate on {project_name}",
                       "Error rate is 12% (threshold: 5%)")
            time.sleep(1)

            fire_alert("HighLatencyP95", "warning", "High P95 latency",
                       "P95 latency is 3.2s for /api/items (threshold: 2s)")
            time.sleep(1)

            print("\\nAll test alerts fired. Check Alertmanager UI at", ALERTMANAGER_URL)
            print("To resolve: run this script again with RESOLVE=1")

            if os.getenv("RESOLVE"):
                time.sleep(2)
                resolve_alert("HighErrorRate")
                resolve_alert("HighLatencyP95")
    """)
    (alerting_dir / "alert_test_script.py").write_text(test_script)

    # ── .env template ─────────────────────────────────────────────────────────
    env_template = textwrap.dedent("""\
        # Alertmanager environment variables
        # Copy this to .env and fill in your values

        # Slack incoming webhook URL
        SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

        # PagerDuty integration key (Events API v2)
        PAGERDUTY_SERVICE_KEY=your-pagerduty-service-key

        # Alertmanager address (for alert_test_script.py)
        ALERTMANAGER_URL=http://localhost:9093
    """)
    (alerting_dir / ".env.alerting.example").write_text(env_template)

    # ── Integration guide ─────────────────────────────────────────────────────
    integration_md = textwrap.dedent("""\
        # Alerting Integration Guide

        ## Files Generated

        | File | Purpose |
        |------|---------|
        | `alertmanager.yml` | Alertmanager routing config (Slack + PagerDuty) |
        | `alert_rules.yml` | Prometheus alert rules |
        | `alert_runbooks/` | Step-by-step incident response guides |
        | `alert_test_script.py` | Fire test alerts to validate routing |
        | `.env.alerting.example` | Environment variable template |

        ## Setup

        ### 1. Configure Alertmanager

        ```bash
        cp .env.alerting.example .env.alerting
        # Edit .env.alerting with your Slack webhook URL and PagerDuty key

        # Add to docker-compose.yml:
        # alertmanager:
        #   image: prom/alertmanager:latest
        #   ports: ["9093:9093"]
        #   volumes:
        #     - ./alerting/alertmanager.yml:/etc/alertmanager/alertmanager.yml
        ```

        ### 2. Load Alert Rules into Prometheus

        ```yaml
        # In prometheus.yml, add:
        rule_files:
          - "alerting/alert_rules.yml"

        alerting:
          alertmanagers:
            - static_configs:
                - targets: ["alertmanager:9093"]
        ```

        ### 3. Test Alert Routing

        ```bash
        # Fire test alerts
        ALERTMANAGER_URL=http://localhost:9093 python alerting/alert_test_script.py

        # Check Alertmanager UI
        open http://localhost:9093
        ```

        ## Alert Thresholds

        | Alert | Threshold | Severity |
        |-------|-----------|----------|
        | HighErrorRate | > 5% 5xx for 2m | Critical |
        | HighLatencyP95 | > 2s for 3m | Warning |
        | DBConnectionPoolExhausted | < 2 connections | Critical |
        | ServiceDown | Unreachable for 1m | Critical |
        | HighMemoryUsage | > 500MB for 5m | Warning |
        | HighCPUUsage | > 80% for 5m | Warning |

        Adjust thresholds in `alert_rules.yml` to match your SLAs.
    """)
    (alerting_dir / "INTEGRATION.md").write_text(integration_md)

    files_written = [
        "alertmanager.yml", "alert_rules.yml",
        "alert_runbooks/HighErrorRate.md", "alert_runbooks/HighLatency.md",
        "alert_runbooks/DBConnectionPoolExhausted.md", "alert_runbooks/ServiceDown.md",
        "alert_test_script.py", ".env.alerting.example", "INTEGRATION.md",
    ]

    return TaskResult(
        output_path=str(alerting_dir),
        confidence=0.9,
        metadata={"files_written": len(files_written), "files": files_written},
        issues=[],
        success=True,
    )
