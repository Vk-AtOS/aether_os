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
    prom_yml = f"""
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'app'
    static_configs:
      - targets: ['localhost:8000']
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
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
        
    # 4. Docker Compose
    dc_yml = """
version: '3.8'
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
  grafana:
    image: grafana/grafana
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
            if "prometheus_client" not in content and "app = FastAPI(" in content:
                _metrics_snippet = (
                    "\ntry:\n"
                    "    from prometheus_fastapi_instrumentator import Instrumentator as _Instr\n"
                    "    _Instr().instrument(app).expose(app)\n"
                    "except ImportError:\n"
                    "    pass  # prometheus_fastapi_instrumentator not installed — metrics disabled\n"
                )
                # Insert after the first `app = FastAPI(` declaration
                content = content.replace(
                    "app = FastAPI(",
                    "app = FastAPI(",
                    1,  # only first occurrence
                )
                _insert_pos = content.find("app = FastAPI(")
                _end_line = content.find("\n", _insert_pos)
                if _end_line > 0:
                    content = content[:_end_line + 1] + _metrics_snippet + content[_end_line + 1:]
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
