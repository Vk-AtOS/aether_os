"""P09 Observability — instruments generated FastAPI apps with Prometheus metrics,
structured JSON logging, and a pre-built monitoring stack (Prometheus + Grafana)."""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_MONITORING_PY = '''\
"""Auto-generated observability for {project_name}."""
from __future__ import annotations
import json
import logging
import sys
import time
from typing import Callable

# ── Structured JSON logging ───────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {{
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }}
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


# ── Prometheus metrics ────────────────────────────────────────────────────────

def add_prometheus_middleware(app) -> None:
    """Expose /metrics endpoint with per-route latency histograms.

    Uses an isolated CollectorRegistry so that multiple pipeline runs in the
    same process don't collide on metric names (ValueError: Duplicated timeseries).
    """
    try:
        from prometheus_client import CollectorRegistry
        from prometheus_fastapi_instrumentator import Instrumentator
        _registry = CollectorRegistry()
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/metrics", "/health"],
            registry=_registry,
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
        logging.getLogger(__name__).info("Prometheus metrics at /metrics")
    except ImportError:
        logging.getLogger(__name__).warning(
            "prometheus-fastapi-instrumentator not installed — /metrics disabled"
        )


# ── Request timing middleware ─────────────────────────────────────────────────

async def timing_middleware(request, call_next: Callable):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{{time.perf_counter() - start:.4f}}s"
    return response
'''

_PROMETHEUS_CONFIG = '''\
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "{project_name}"
    static_configs:
      - targets: ["host.docker.internal:8000"]
    metrics_path: /metrics
'''

_DOCKER_COMPOSE_MONITORING = '''\
# Optional monitoring overlay
# Usage: docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
version: "3.9"
services:
  prometheus:
    image: prom/prometheus:v2.51.0
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=15d"

  grafana:
    image: grafana/grafana:10.4.1
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "admin"
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
    ports:
      - "3001:3000"
    depends_on: [prometheus]

volumes:
  prometheus_data:
  grafana_data:
'''

_GRAFANA_DATASOURCE = '''\
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    access: proxy
'''

_GRAFANA_DASH_PROVISION = '''\
apiVersion: 1
providers:
  - name: default
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    options:
      path: /etc/grafana/provisioning/dashboards
'''


def _find_backend_src(data: dict) -> Path | None:
    """Find the canonical backend src dir where p11 will build from.

    Problem 72: p09 must patch the same canonical_src_dir that p11 builds from
    (p04_backend/backend_codegen/src), NOT the scaffolding dir (p03_scaffolding/*/src).
    Priority order:
      1. canonical_src_dir from pipeline context (set by p04a)
      2. backend_src_dir from pipeline context
      3. p04_backend/backend_codegen/src (standard p04a output location)
      4. main_py parent
      5. project_dir rglob fallback (prefer deeper paths = generated code)
    """
    # Priority 1+2: explicit canonical path from pipeline
    for key in ("canonical_src_dir", "backend_src_dir"):
        val = data.get(key, "")
        if val:
            p = Path(val)
            if p.is_file():
                p = p.parent
            if p.is_dir() and (p / "main.py").exists():
                return p

    # Priority 3: standard p04a output location
    project_dir = data.get("project_dir", "")
    if project_dir:
        _standard = Path(project_dir) / "p04_backend" / "backend_codegen" / "src"
        if _standard.is_dir() and (_standard / "main.py").exists():
            return _standard
        # Also check p04a_backend_codegen/src
        _alt = Path(project_dir) / "p04a_backend_codegen" / "src"
        if _alt.is_dir() and (_alt / "main.py").exists():
            return _alt

    # Priority 4: main_py direct path
    val = data.get("main_py", "")
    if val:
        p = Path(val)
        if p.is_file():
            p = p.parent
        if p.is_dir() and (p / "main.py").exists():
            return p

    # Priority 5: project_dir rglob — prefer deeper candidates (generated code over stubs)
    # and exclude node_modules/p03_scaffolding to avoid patching stubs
    if project_dir:
        _candidates = [
            c for c in Path(project_dir).rglob("main.py")
            if "node_modules" not in str(c)
            and "p03_scaffolding" not in str(c)
        ]
        if _candidates:
            # Prefer deeper paths (more specific subdirectories = real generated code)
            _candidates.sort(key=lambda x: -len(x.parts))
            return _candidates[0].parent
    return None


def _patch_main_py(main_py: Path) -> None:
    source = main_py.read_text()
    # Problem 72: use absolute import (no relative dot) so it works in Docker (PYTHONPATH=/app)
    if "from monitoring import" in source or "from .monitoring import" in source:
        # Fix relative import if present
        source = source.replace("from .monitoring import", "from monitoring import")
        main_py.write_text(source)
        return
    import_line = "from monitoring import setup_logging, add_prometheus_middleware, timing_middleware\n"
    if "from __future__ import annotations" in source:
        source = source.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n" + import_line,
            1,
        )
    else:
        source = import_line + source

    # setup_logging() — inject before lifespan or at module level
    if "setup_logging()" not in source:
        if "async def lifespan" in source:
            source = re.sub(
                r"(async def lifespan)",
                "setup_logging()\n\n\\1",
                source, count=1,
            )
        else:
            source += "\n\nsetup_logging()\n"

    # Prometheus + timing — add after app = FastAPI(...)
    if "add_prometheus_middleware(app)" not in source:
        source += "\nadd_prometheus_middleware(app)\n"
    if "timing_middleware" not in source:
        source += "\napp.middleware('http')(timing_middleware)\n"

    main_py.write_text(source)


async def run(phase_input: Any, memory_ctx: List[dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    backend_src_dir = _find_backend_src(data)

    files_written: list[str] = []

    # 1. Inject monitoring.py into generated backend
    if backend_src_dir:
        mon_path = backend_src_dir / "monitoring.py"
        mon_path.write_text(_MONITORING_PY.format(project_name=project_name))
        files_written.append(str(mon_path))

        main_py = backend_src_dir / "main.py"
        if main_py.exists():
            try:
                _patch_main_py(main_py)
                files_written.append(str(main_py) + " [patched]")
            except Exception as exc:
                logger.warning("[p09] Could not patch main.py: %s", exc)

        # Patch requirements.txt to include prometheus instrumentator
        for req_path in [
            backend_src_dir.parent / "requirements.txt",
            backend_src_dir / "requirements.txt",
        ]:
            if req_path.exists():
                content = req_path.read_text()
                if "prometheus-fastapi-instrumentator" not in content:
                    req_path.write_text(content.rstrip() + "\nprometheus-fastapi-instrumentator>=0.9.1\n")
                    files_written.append(str(req_path) + " [patched]")
                break

    # 2. Write Prometheus + Grafana monitoring stack
    mon_dir = output_dir / "monitoring"
    mon_dir.mkdir(exist_ok=True)
    (mon_dir / "prometheus.yml").write_text(_PROMETHEUS_CONFIG.format(project_name=project_name))
    (mon_dir / "docker-compose.monitoring.yml").write_text(_DOCKER_COMPOSE_MONITORING)

    ds_dir = mon_dir / "grafana" / "datasources"
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "prometheus.yml").write_text(_GRAFANA_DATASOURCE)

    db_dir = mon_dir / "grafana" / "dashboards"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "provisioning.yml").write_text(_GRAFANA_DASH_PROVISION)

    files_written += [
        str(mon_dir / "prometheus.yml"),
        str(mon_dir / "docker-compose.monitoring.yml"),
        str(ds_dir / "prometheus.yml"),
        str(db_dir / "provisioning.yml"),
    ]

    # Problem 69: verify all four observability components were actually generated
    _gate_issues = []
    _features_present = []

    # Component 1: structured JSON logging in monitoring.py
    if backend_src_dir:
        _mon_py = backend_src_dir / "monitoring.py"
        if _mon_py.exists() and "JsonFormatter" in _mon_py.read_text():
            _features_present.append("structured_json_logging")
        else:
            _gate_issues.append("structured JSON logging not injected into monitoring.py")

        # Component 2: Prometheus /metrics endpoint
        _main_py_check = backend_src_dir / "main.py"
        if _main_py_check.exists() and (
            "add_prometheus_middleware" in _main_py_check.read_text()
            or "prometheus" in _main_py_check.read_text().lower()
        ):
            _features_present.append("prometheus_metrics")
        else:
            _gate_issues.append("Prometheus /metrics endpoint not wired into main.py")
    else:
        _gate_issues.append("No backend src dir found — cannot instrument logging or metrics")

    # Component 3: prometheus_alerts.yml — write it if missing
    _alerts_file = output_dir / "monitoring" / "prometheus_alerts.yml"
    if not _alerts_file.exists():
        _alerts_content = f"""\
groups:
  - name: {project_name}_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{{status=~"5.."}}[5m]) > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High 5xx error rate on {project_name}"
          description: "More than 10% of requests are failing."

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High p95 latency on {project_name}"
          description: "95th percentile response time exceeded 2 seconds."

      - alert: ServiceDown
        expr: up{{job="{project_name}"}} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "{project_name} is down"
          description: "The service has been unreachable for 1 minute."
"""
        try:
            _alerts_file.parent.mkdir(parents=True, exist_ok=True)
            _alerts_file.write_text(_alerts_content)
            files_written.append(str(_alerts_file))
            _features_present.append("prometheus_alerts")
        except Exception as _ae:
            _gate_issues.append(f"prometheus_alerts.yml generation failed: {_ae}")
    else:
        _features_present.append("prometheus_alerts")

    # Component 4: OpenTelemetry instrumentation
    _otel_py = output_dir / "monitoring" / "otel_setup.py"
    if not _otel_py.exists():
        _otel_content = f"""\
\"\"\"OpenTelemetry instrumentation for {project_name}.\"\"\"
from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)


def setup_opentelemetry(app) -> None:
    \"\"\"Instrument FastAPI app with OpenTelemetry tracing.\"\"\"
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        provider = TracerProvider()
        exporter = OTLPSpanExporter(endpoint=f"{{otlp_endpoint}}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        try:
            SQLAlchemyInstrumentor().instrument()
        except Exception:
            pass
        logger.info("OpenTelemetry tracing enabled — exporting to %s", otlp_endpoint)
    except ImportError:
        logger.warning(
            "OpenTelemetry not installed — tracing disabled. "
            "Install with: pip install opentelemetry-sdk opentelemetry-instrumentation-fastapi"
        )
"""
        try:
            _otel_py.write_text(_otel_content)
            files_written.append(str(_otel_py))
            _features_present.append("opentelemetry_tracing")
        except Exception as _oe:
            _gate_issues.append(f"OpenTelemetry setup file generation failed: {_oe}")
    else:
        _features_present.append("opentelemetry_tracing")

    gate_passed = len(_gate_issues) == 0

    summary = {
        "project": project_name,
        "backend_src": str(backend_src_dir) if backend_src_dir else None,
        "files_written": len(files_written),
        "files": files_written,
        "features": _features_present,
        "gate_passed": gate_passed,
        "gate_issues": _gate_issues,
    }
    summary_path = output_dir / "observability.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    logger.info("[p09] observability complete: %d files written, gate_passed=%s, issues=%s",
                len(files_written), gate_passed, _gate_issues)

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.9 if gate_passed else 0.5,
        metadata=summary,
        success=gate_passed,
        issues=_gate_issues,
    )
