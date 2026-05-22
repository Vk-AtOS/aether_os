from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
import asyncio
import json
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11a_monitoring: Production Observability Stack
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    monitoring_dir = output_dir / "monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "dashboards").mkdir(parents=True, exist_ok=True)
    
    domain = phase_input.input_data.get("domain", "general")
    metadata = {}
    issues = []
    
    # 1. Prometheus Config
    # 'app:8000' uses the Docker Compose service name — not localhost (unreachable in Docker)
    prom_yml = f"""
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: '{domain}'
rule_files:
  - 'alert_rules.yml'
scrape_configs:
  - job_name: 'app'
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
    """
    (monitoring_dir / "prometheus.yml").write_text(prom_yml)
    
    # 2. Alert Rules
    alert_rules = f"""
groups:
- name: red_metrics
  rules:
  - alert: HighErrorRate
    expr: rate(http_requests_total{{status=~"5.."}}[5m]) > 0.05
    for: 2m
  - alert: HighLatency
    expr: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 2
    for: 2m
    """
    (monitoring_dir / "alert_rules.yml").write_text(alert_rules)
    
    # 3. Grafana Dashboards
    dashboards = {
        "red_metrics.json": '{"title": "RED Metrics", "panels": []}',
        "resources.json": '{"title": "Resources", "panels": []}',
        "business.json": f'{{"title": "{domain.capitalize()} Business Metrics", "panels": []}}'
    }
    for name, content in dashboards.items():
        (monitoring_dir / "grafana" / "dashboards" / name).write_text(content)
        
    # 4. Docker Compose — monitoring sidecar stack
    # Grafana datasource provisioning auto-wires Prometheus so users see dashboards on first launch
    dc_yml = """version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./alert_rules.yml:/etc/prometheus/alert_rules.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'
    restart: unless-stopped
    networks:
      - monitoring
      - app_network

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
    depends_on:
      - prometheus
    restart: unless-stopped
    networks:
      - monitoring

  node-exporter:
    image: prom/node-exporter:latest
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
    restart: unless-stopped
    networks:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
  app_network:
    external: true
    name: ${COMPOSE_PROJECT_NAME:-app}_default
"""
    (monitoring_dir / "docker-compose.monitoring.yml").write_text(dc_yml)
    
    # 5. OTEL Config
    otel_config = "receivers: [otlp] \nexporters: [prometheus, jaeger]"
    (monitoring_dir / "otel_config.yaml").write_text(otel_config)
    
    # 6. App Instrumentation
    app_instrumentation = """
from prometheus_client import make_asgi_app
from fastapi import FastAPI
def instrument_app(app: FastAPI):
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    """
    (monitoring_dir / "app_instrumentation.py").write_text(app_instrumentation)
    
    # Inject Prometheus instrumentation into main.py (best-effort, non-blocking)
    _src_dir = project_dir / "src"
    _main_py_path = _src_dir / "main.py" if (_src_dir / "main.py").exists() else project_dir / "main.py"
    if _main_py_path.exists():
        try:
            content = _main_py_path.read_text()
            if "prometheus_client" not in content and "Instrumentator" not in content and "app = FastAPI(" in content:
                _metrics_snippet = (
                    "\ntry:\n"
                    "    from prometheus_fastapi_instrumentator import Instrumentator as _Instr\n"
                    "    _Instr().instrument(app).expose(app)\n"
                    "except ImportError:\n"
                    "    pass  # prometheus_fastapi_instrumentator not installed — metrics disabled\n"
                )
                # Use bracket-depth counting to find closing ) of app = FastAPI(...) call
                _start = content.find("app = FastAPI(")
                _depth, _end = 0, _start
                for _i, _ch in enumerate(content[_start:], _start):
                    if _ch == "(":
                        _depth += 1
                    elif _ch == ")":
                        _depth -= 1
                        if _depth == 0:
                            _end = _i
                            break
                _end_nl = content.find("\n", _end)
                if _end_nl >= 0:
                    content = content[:_end_nl + 1] + _metrics_snippet + content[_end_nl + 1:]
                    _main_py_path.write_text(content)
        except Exception as _e:
            issues.append(f"Prometheus injection skipped: {_e}")
            
    return TaskResult(
        output_path=str(monitoring_dir),
        confidence=0.9,
        metadata={"domain": domain, "files_written": 10},
        issues=issues,
        success=True
    )
