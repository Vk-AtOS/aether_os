"""P11a Task Agent — generate prometheus + grafana monitoring configs."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    arch_json = data.get("architecture_json", {})
    project_name = data.get("project_name", "app")
    project_dir = Path(data.get("project_dir", str(output_dir)))
    domain = data.get("domain", "general")
    llm = get_llm_client()

    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)

    mon_dir = output_dir / "monitoring"
    mon_dir.mkdir(exist_ok=True)
    grafana_dir = mon_dir / "grafana" / "dashboards"
    grafana_dir.mkdir(parents=True, exist_ok=True)

    # alert_rules.yml
    alert_rules = f"""groups:
  - name: {project_name}_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{{status=~"5.."}}[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected on {project_name}"
"""
    if domain == "industrial":
        alert_rules += """
      - alert: SensorThresholdExceeded
        expr: sensor_reading_value > 90
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Industrial sensor threshold exceeded"
"""
    (mon_dir / "alert_rules.yml").write_text(alert_rules)

    # prometheus.yml
    prometheus_yml = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "{project_name}"
    static_configs:
      - targets: ["app:8000"]
    metrics_path: /metrics
"""
    if domain == "saas_multitenant":
        prometheus_yml += """
    metric_relabel_configs:
      - source_labels: [org_id]
        target_label: tenant
"""
    
    prometheus_yml += """
  - job_name: "node_exporter"
    static_configs:
      - targets: ["node-exporter:9100"]

  - job_name: "postgres_exporter"
    static_configs:
      - targets: ["postgres-exporter:9187"]

rule_files:
  - "alert_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
"""
    (mon_dir / "prometheus.yml").write_text(prometheus_yml)

    # Grafana dashboards
    red_dashboard = {
        "title": f"{project_name} RED Metrics",
        "panels": [
            {"title": "Request Rate", "type": "graph", "targets": [{"expr": "rate(http_requests_total[5m])"}]},
            {"title": "Error Rate", "type": "graph", "targets": [{"expr": "rate(http_requests_total{status=~\"5..\"}[5m])"}]},
            {"title": "P95 Latency", "type": "graph", "targets": [{"expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}]},
        ]
    }
    
    if domain == "saas_multitenant":
        red_dashboard["panels"].append({
            "title": "Requests per Tenant",
            "type": "graph",
            "targets": [{"expr": "sum by (org_id) (rate(http_requests_total[5m]))"}]
        })
    elif domain == "industrial":
        red_dashboard["panels"].append({
            "title": "Sensor Activity",
            "type": "graph",
            "targets": [{"expr": "rate(sensor_reading_total[5m])"}]
        })

    resources_dashboard = {
        "title": f"{project_name} Resources",
        "panels": [
            {"title": "CPU Usage", "type": "graph", "targets": [{"expr": "100 - (avg(rate(node_cpu_seconds_total{{mode=\"idle\"}}[5m])) * 100)"}]},
            {"title": "Memory Usage", "type": "graph", "targets": [{"expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100"}]},
            {"title": "Disk Usage", "type": "graph", "targets": [{"expr": "(1 - (node_filesystem_free_bytes / node_filesystem_size_bytes)) * 100"}]},
        ]
    }
    (grafana_dir / "red_metrics.json").write_text(json.dumps(red_dashboard, indent=2))
    (grafana_dir / "resources.json").write_text(json.dumps(resources_dashboard, indent=2))

    # docker-compose.monitoring.yml
    compose_mon = f"""version: '3.8'
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./monitoring/alert_rules.yml:/etc/prometheus/alert_rules.yml
    ports: ["9090:9090"]
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${{GRAFANA_PASSWORD:-admin}}
    volumes:
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards
    ports: ["3001:3000"]
  alertmanager:
    image: prom/alertmanager:latest
    ports: ["9093:9093"]
  node-exporter:
    image: prom/node-exporter:latest
    ports: ["9100:9100"]
"""
    (project_dir / "docker-compose.monitoring.yml").write_text(compose_mon)

    # Add /metrics to application
    metrics_snippet = """
# Add to main.py — prometheus metrics
from prometheus_client import make_asgi_app, Counter, Histogram, generate_latest
import time

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["endpoint"])

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    REQUEST_LATENCY.labels(request.url.path).observe(time.time() - start)
    return response

@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(generate_latest(), media_type="text/plain")
"""
    metrics_path = output_dir / "metrics_snippet.py"
    metrics_path.write_text(metrics_snippet)

    # Apply metrics to main.py if found
    main_py = project_dir / "src" / "main.py"
    if main_py.exists() and "/metrics" not in main_py.read_text():
        main_py.write_text(main_py.read_text() + metrics_snippet)

    issues = []
    if not (mon_dir / "prometheus.yml").exists():
        issues.append("prometheus.yml not written")
    dashboards = list(grafana_dir.glob("*.json"))
    if len(dashboards) < 2:
        issues.append(f"Only {len(dashboards)} grafana dashboards (need >= 2)")

    return TaskResult(
        output_path=str(mon_dir),
        confidence=0.9 if not issues else 0.5,
        metadata={"prometheus_ok": True, "dashboard_count": len(dashboards)},
        issues=issues,
        success=len(issues) == 0,
    )
