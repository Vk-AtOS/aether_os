"""KAN-100 p09/p11a/p11d: one metrics instrumentator, OpenTelemetry actually wired, Alertmanager secrets from files."""
import asyncio
import textwrap
from types import SimpleNamespace

import yaml

from aether_os.phases.p09_observability import task_agent as p09
from aether_os.phases.p11a_monitoring import task_agent as p11a
from aether_os.phases.p11d_alerting import task_agent as p11d


def test_alertmanager_config_has_no_unexpanded_env_references(tmp_path):
    asyncio.run(p11d.run(SimpleNamespace(input_data={"project_name": "demo"}), [], tmp_path))
    text = (tmp_path / "alerting" / "alertmanager.yml").read_text()
    assert "${" not in text            # Alertmanager does not expand them: the literal text was sent as the URL
    cfg = yaml.safe_load(text)
    assert cfg["global"]["slack_api_url_file"].endswith("slack_webhook_url")
    pd = next(r for r in cfg["receivers"] if r["name"] == "pagerduty")["pagerduty_configs"][0]
    assert pd["service_key_file"].endswith("pagerduty_service_key")


def test_p09_wires_opentelemetry_and_does_not_add_a_second_instrumentator(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    asyncio.run(p09.run(SimpleNamespace(input_data={"project_name": "demo", "backend_src_dir": str(src)}), [], tmp_path / "out"))
    main = (src / "main.py").read_text()
    assert "setup_opentelemetry(app)" in main and (src / "otel_setup.py").exists()
    compile(main, "main.py", "exec")
    compile((src / "otel_setup.py").read_text(), "otel_setup.py", "exec")
    # an app that already serves /metrics must not get a second Instrumentator
    from fastapi import FastAPI
    app = FastAPI()
    app.add_api_route("/metrics", lambda: "x")
    before = len(app.user_middleware)
    ns = {"__name__": "monitoring"}
    exec(compile((src / "monitoring.py").read_text(), "monitoring.py", "exec"), ns)
    ns["add_prometheus_middleware"](app)
    assert len(app.user_middleware) == before


def test_p11a_helper_skips_when_metrics_exist(tmp_path):
    asyncio.run(p11a.run(SimpleNamespace(input_data={"project_name": "demo"}), [], tmp_path))
    ns = {}
    exec(textwrap.dedent((tmp_path / "monitoring" / "app_instrumentation.py").read_text()), ns)
    from fastapi import FastAPI
    app = FastAPI()
    app.add_api_route("/metrics", lambda: "x")
    before = len(app.user_middleware)
    ns["instrument_app"](app)
    assert len(app.user_middleware) == before
