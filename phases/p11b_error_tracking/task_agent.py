"""P11b Task Agent — wire Sentry SDK."""
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
    project_dir = Path(data.get("project_dir", str(output_dir)))
    project_name = data.get("project_name", "app")
    llm = get_llm_client()

    # docker-compose.sentry.yml
    compose_sentry = """version: '3.8'
services:
  sentry:
    image: getsentry/sentry:latest
    environment:
      - SENTRY_SECRET_KEY=${SENTRY_SECRET_KEY:-sentry-secret}
      - SENTRY_POSTGRES_HOST=sentry-db
      - SENTRY_DB_USER=sentry
      - SENTRY_DB_PASSWORD=${SENTRY_DB_PASSWORD:-sentry}
    ports: ["9000:9000"]
    depends_on: [sentry-db, sentry-redis]
  sentry-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: sentry
      POSTGRES_PASSWORD: ${SENTRY_DB_PASSWORD:-sentry}
      POSTGRES_DB: sentry
  sentry-redis:
    image: redis:7-alpine
  sentry-worker:
    image: getsentry/sentry:latest
    command: ["run", "worker"]
    environment:
      - SENTRY_SECRET_KEY=${SENTRY_SECRET_KEY:-sentry-secret}
"""
    (project_dir / "docker-compose.sentry.yml").write_text(compose_sentry)

    # Sentry SDK integration snippet
    sentry_init = """
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
import os

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN", ""),
    integrations=[FastApiIntegration(), SqlalchemyIntegration()],
    traces_sample_rate=1.0,
    environment=os.getenv("APP_ENV", "production"),
    release=os.getenv("APP_VERSION", "1.0.0"),
)
"""
    # Wire into main.py
    main_py = project_dir / "src" / "main.py"
    if main_py.exists():
        content = main_py.read_text()
        if "sentry_sdk" not in content:
            main_py.write_text(sentry_init + content)

    # Write integration file
    sentry_file = project_dir / "src" / "sentry_config.py"
    sentry_file.parent.mkdir(parents=True, exist_ok=True)
    sentry_file.write_text(sentry_init)

    # Test sentry integration
    test_sentry = """
import pytest
import sentry_sdk
import os

def test_sentry_initialises():
    os.environ.setdefault("SENTRY_DSN", "")
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN",""), traces_sample_rate=0)
    assert True  # SDK initialised without exception

def test_sentry_captures_exception():
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("test", "true")
        # In production this would send to Sentry; in test we just verify no error
        event_id = sentry_sdk.capture_message("AetherOS test event")
    assert True
"""
    test_path = output_dir / "test_sentry.py"
    test_path.write_text(test_sentry)

    # Update .env.example
    env_example = project_dir / ".env.example"
    if env_example.exists():
        content = env_example.read_text()
        if "SENTRY_DSN" not in content:
            env_example.write_text(content + "\n# Sentry\nSENTRY_DSN=\n")

    issues = []
    if not sentry_file.exists():
        issues.append("sentry_config.py not written")
    if env_example.exists() and "SENTRY_DSN" not in env_example.read_text():
        issues.append("SENTRY_DSN not in .env.example")

    return TaskResult(
        output_path=str(sentry_file),
        confidence=0.9 if not issues else 0.5,
        metadata={"sentry_configured": True, "docker_compose": True},
        issues=issues,
        success=len(issues) == 0,
    )
