from __future__ import annotations
import json
import logging
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """P11a monitoring: Prometheus + Grafana + OTEL observability stack."""
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    project_name = phase_input.input_data.get("project_name", "app")
    domain = phase_input.input_data.get("domain", "general")
    monitoring_dir = output_dir / "monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "dashboards").mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "provisioning" / "datasources").mkdir(parents=True, exist_ok=True)
    issues = []

    # ── Prometheus config ─────────────────────────────────────────────────────
    prom_yml = textwrap.dedent(f"""\
        global:
          scrape_interval: 15s
          evaluation_interval: 15s

        rule_files:
          - "alert_rules.yml"

        scrape_configs:
          - job_name: '{project_name}'
            static_configs:
              - targets: ['app:8000']
            metrics_path: /metrics

          - job_name: 'node-exporter'
            static_configs:
              - targets: ['node-exporter:9100']
    """)
    (monitoring_dir / "prometheus.yml").write_text(prom_yml)

    # ── Alert rules ───────────────────────────────────────────────────────────
    alert_rules = textwrap.dedent(f"""\
        groups:
          - name: {project_name}_api
            interval: 30s
            rules:
              - alert: HighErrorRate
                expr: |
                  (sum(rate(http_requests_total{{status=~"5.."}}[5m]))
                   / sum(rate(http_requests_total[5m]))) > 0.05
                for: 2m
                labels:
                  severity: critical
                annotations:
                  summary: "High error rate on {project_name}"
                  description: "Error rate is {{{{ $value | humanizePercentage }}}}"

              - alert: HighP95Latency
                expr: |
                  histogram_quantile(0.95,
                    sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
                  ) > 2.0
                for: 3m
                labels:
                  severity: warning
                annotations:
                  summary: "High P95 latency on {project_name}"
                  description: "P95 = {{{{ $value }}}}s"

              - alert: ServiceDown
                expr: up == 0
                for: 1m
                labels:
                  severity: critical
                annotations:
                  summary: "{project_name} is down"
    """)
    (monitoring_dir / "alert_rules.yml").write_text(alert_rules)

    # ── Grafana dashboard (real panels) ───────────────────────────────────────
    red_dashboard = {
        "uid": "red-metrics",
        "title": f"{project_name} — RED Metrics",
        "tags": ["red", "api"],
        "timezone": "browser",
        "refresh": "30s",
        "panels": [
            {
                "id": 1, "title": "Request Rate (req/s)",
                "type": "graph", "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                "targets": [{"expr": "sum(rate(http_requests_total[1m]))", "legendFormat": "req/s"}]
            },
            {
                "id": 2, "title": "Error Rate (%)",
                "type": "graph", "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
                "targets": [{"expr": "sum(rate(http_requests_total{status=~'5..'}[1m])) / sum(rate(http_requests_total[1m])) * 100", "legendFormat": "error %"}]
            },
            {
                "id": 3, "title": "P95 Latency (s)",
                "type": "graph", "gridPos": {"x": 0, "y": 8, "w": 12, "h": 8},
                "targets": [{"expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))", "legendFormat": "p95"}]
            },
            {
                "id": 4, "title": "P99 Latency (s)",
                "type": "graph", "gridPos": {"x": 12, "y": 8, "w": 12, "h": 8},
                "targets": [{"expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))", "legendFormat": "p99"}]
            },
        ]
    }
    (monitoring_dir / "grafana" / "dashboards" / "red_metrics.json").write_text(
        json.dumps(red_dashboard, indent=2)
    )

    resources_dashboard = {
        "uid": "resources",
        "title": f"{project_name} — Resources",
        "tags": ["resources", "infra"],
        "refresh": "30s",
        "panels": [
            {
                "id": 1, "title": "CPU Usage",
                "type": "graph", "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                "targets": [{"expr": "rate(process_cpu_seconds_total[1m]) * 100", "legendFormat": "cpu %"}]
            },
            {
                "id": 2, "title": "Memory (MB)",
                "type": "graph", "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
                "targets": [{"expr": "process_resident_memory_bytes / 1024 / 1024", "legendFormat": "MB"}]
            },
        ]
    }
    (monitoring_dir / "grafana" / "dashboards" / "resources.json").write_text(
        json.dumps(resources_dashboard, indent=2)
    )

    business_dashboard = {
        "uid": "business-kpis",
        "title": f"{project_name} — Business KPIs",
        "tags": ["business", "kpis"],
        "refresh": "1m",
        "panels": [
            {
                "id": 1, "title": "Active Users (24h)",
                "type": "stat", "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
                "targets": [{"expr": "sum(increase(http_requests_total[24h]))", "legendFormat": "requests"}]
            },
            {
                "id": 2, "title": "API Availability (%)",
                "type": "gauge", "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
                "targets": [{"expr": "avg_over_time(up[24h]) * 100", "legendFormat": "uptime %"}]
            },
            {
                "id": 3, "title": "Requests by Endpoint",
                "type": "table", "gridPos": {"x": 0, "y": 4, "w": 24, "h": 8},
                "targets": [{"expr": "topk(10, sum by (handler) (rate(http_requests_total[5m])))", "legendFormat": "{{handler}}"}]
            },
        ]
    }
    (monitoring_dir / "grafana" / "dashboards" / "business_kpis.json").write_text(
        json.dumps(business_dashboard, indent=2)
    )

    # ── Domain-specific Grafana dashboard ─────────────────────────────────────
    try:
        from aether_os.phases.p11a_monitoring.grafana_domain_dashboards import get_domain_dashboard
        _domain_dash = get_domain_dashboard(domain, project_name)
        if _domain_dash:
            _fname = f"domain_{domain.lower().replace('-','_').replace(' ','_')}.json"
            (monitoring_dir / "grafana" / "dashboards" / _fname).write_text(
                json.dumps(_domain_dash, indent=2)
            )
    except Exception as _dd_exc:
        issues.append(f"domain dashboard skipped: {_dd_exc}")

    # ── Grafana provisioning ──────────────────────────────────────────────────
    datasource_config = textwrap.dedent("""\
        apiVersion: 1
        datasources:
          - name: Prometheus
            type: prometheus
            access: proxy
            url: http://prometheus:9090
            isDefault: true
            editable: false
    """)
    (monitoring_dir / "grafana" / "provisioning" / "datasources" / "prometheus.yml").write_text(
        datasource_config
    )

    dashboard_provisioning = textwrap.dedent("""\
        apiVersion: 1
        providers:
          - name: default
            type: file
            options:
              path: /var/lib/grafana/dashboards
    """)
    (monitoring_dir / "grafana" / "provisioning" / "dashboards").mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "provisioning" / "dashboards" / "default.yml").write_text(
        dashboard_provisioning
    )

    # ── Docker Compose (monitoring stack) ─────────────────────────────────────
    dc_yml = textwrap.dedent("""\
        version: '3.8'

        services:
          prometheus:
            image: prom/prometheus:latest
            volumes:
              - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
              - ./alert_rules.yml:/etc/prometheus/alert_rules.yml:ro
              - prometheus_data:/prometheus
            command:
              - '--config.file=/etc/prometheus/prometheus.yml'
              - '--storage.tsdb.path=/prometheus'
              - '--web.enable-lifecycle'
            ports:
              - "9090:9090"
            restart: unless-stopped

          grafana:
            image: grafana/grafana:latest
            environment:
              - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
              - GF_USERS_ALLOW_SIGN_UP=false
            volumes:
              - grafana_data:/var/lib/grafana
              - ./grafana/provisioning:/etc/grafana/provisioning:ro
              - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
            ports:
              - "3001:3000"
            depends_on:
              - prometheus
            restart: unless-stopped

          node-exporter:
            image: prom/node-exporter:latest
            volumes:
              - /proc:/host/proc:ro
              - /sys:/host/sys:ro
              - /:/rootfs:ro
            command:
              - '--path.procfs=/host/proc'
              - '--path.rootfs=/rootfs'
              - '--path.sysfs=/host/sys'
            restart: unless-stopped

        volumes:
          prometheus_data:
          grafana_data:
    """)
    (monitoring_dir / "docker-compose.monitoring.yml").write_text(dc_yml)

    # ── OTEL Collector config ─────────────────────────────────────────────────
    otel_config = textwrap.dedent("""\
        receivers:
          otlp:
            protocols:
              grpc:
                endpoint: 0.0.0.0:4317
              http:
                endpoint: 0.0.0.0:4318

        processors:
          batch:
            timeout: 1s

        exporters:
          prometheus:
            endpoint: "0.0.0.0:8889"
          logging:
            verbosity: detailed

        service:
          pipelines:
            traces:
              receivers: [otlp]
              processors: [batch]
              exporters: [logging]
            metrics:
              receivers: [otlp]
              processors: [batch]
              exporters: [prometheus]
    """)
    (monitoring_dir / "otel_config.yaml").write_text(otel_config)

    # ── App instrumentation helper ────────────────────────────────────────────
    app_instrumentation = textwrap.dedent("""\
        from fastapi import FastAPI


        def instrument_app(app: FastAPI) -> FastAPI:
            \"\"\"Wire up Prometheus FastAPI instrumentator.  Call after app = FastAPI(...).\"\"\"
            if any(getattr(r, "path", "") == "/metrics" for r in app.routes):
                return app  # already exposed: a second Instrumentator counts every request twice
            try:
                from prometheus_fastapi_instrumentator import Instrumentator
                Instrumentator(
                    should_group_status_codes=True,
                    should_ignore_untemplated=True,
                    should_group_untemplated=True,
                    should_respect_env_var=True,
                    excluded_handlers=["/metrics", "/health"],
                ).instrument(app).expose(app, include_in_schema=False)
            except ImportError:
                pass  # optional dependency — metrics endpoint silently disabled
            return app
    """)
    (monitoring_dir / "app_instrumentation.py").write_text(app_instrumentation)

    # ── Integration guide ─────────────────────────────────────────────────────
    guide = textwrap.dedent("""\
        # Monitoring Setup

        ## Quick Start

        ```bash
        cd monitoring
        docker-compose -f docker-compose.monitoring.yml up -d
        ```

        | Service | URL | Default Login |
        |---------|-----|---------------|
        | Prometheus | http://localhost:9090 | — |
        | Grafana | http://localhost:3001 | admin / admin |

        ## App Integration

        Add `prometheus-fastapi-instrumentator` to requirements.txt, then in `src/main.py`:

        ```python
        from monitoring.app_instrumentation import instrument_app
        app = FastAPI(...)
        instrument_app(app)
        ```

        ## Alert Rules

        Alert rules are in `alert_rules.yml`. Loaded automatically by Prometheus.
        To test: `curl -X POST http://localhost:9090/-/reload`
    """)
    (monitoring_dir / "MONITORING.md").write_text(guide)

    # ── Inject Prometheus instrumentation into main.py ────────────────────────
    _src_dir = project_dir / "src"
    _main_py_path = _src_dir / "main.py" if (_src_dir / "main.py").exists() else project_dir / "main.py"
    if _main_py_path.exists():
        try:
            content = _main_py_path.read_text()
            if "Instrumentator" not in content and "/metrics" not in content and "app = FastAPI(" in content:
                _metrics_snippet = (
                    "\ntry:\n"
                    "    from prometheus_fastapi_instrumentator import Instrumentator as _Instr\n"
                    "    _Instr().instrument(app).expose(app)\n"
                    "except ImportError:\n"
                    "    pass  # prometheus_fastapi_instrumentator not installed — metrics disabled\n"
                )
                # Find the end of the app = FastAPI(...) block (handles multi-line)
                _start = content.find("app = FastAPI(")
                if _start >= 0:
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
            logger.warning("p11a_monitoring: Prometheus injection failed: %s", _e)
            issues.append(f"Prometheus injection skipped: {_e}")

    # PIPELINE-039: count files actually written instead of hardcoding
    files_written = len([f for f in output_dir.rglob("*") if f.is_file()])
    return TaskResult(
        output_path=str(monitoring_dir),
        confidence=0.9,
        metadata={"domain": domain, "files_written": files_written, "grafana_dashboards": 3, "project": project_name},
        issues=issues,
        success=True,
    )
