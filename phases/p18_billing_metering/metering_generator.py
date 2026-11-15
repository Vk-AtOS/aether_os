"""
OpenMeter + Stripe billing/metering infrastructure generator for P18.

Generates:
  - OpenMeter YAML config with per-entity meters
  - CloudEvents JSON schema for metering events
  - FastAPI Stripe webhook handler
  - FastAPI async metering middleware
  - OpenMeter Helm values
  - Complete billing package under output_dir/billing/

Output layout (under output_dir/billing/):
  openmeter-config.yaml
  event-schema.json
  billing_webhook.py
  metering_middleware.py
  helm/openmeter-values.yaml
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.p18_billing_metering.stripe_webhook_generator import generate_stripe_webhook_handler

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


# ── OpenMeter config ──────────────────────────────────────────────────────────


def generate_openmeter_config(slug: str, entities: List[Dict[str, Any]]) -> str:
    """
    OpenMeter YAML config with one meter per entity.
    API calls → COUNT; storage-related entities → SUM; user/account → UNIQUE_COUNT.
    """
    meter_lines: List[str] = []
    storage_keywords = {"file", "storage", "document", "asset", "blob", "upload"}
    user_keywords = {"user", "account", "member", "tenant", "customer", "subscriber"}

    for ent in entities:
        table = ent.get("table", "resource")
        snake = _snake(table)

        # Choose aggregation based on entity name semantics
        if any(kw in snake for kw in user_keywords):
            aggregation = "UNIQUE_COUNT"
            meter_name = f"active_{snake}s"
            unit = "users"
        elif any(kw in snake for kw in storage_keywords):
            aggregation = "SUM"
            meter_name = f"{snake}_storage_gb"
            unit = "GB"
        else:
            aggregation = "COUNT"
            meter_name = f"{snake}_api_calls"
            unit = "requests"

        meter_lines.append(f"""\
  - slug: {meter_name}
    description: "Metering for {table} — {unit}"
    eventType: com.{slug}.{snake}.metered
    aggregation: {aggregation}
    valueProperty: $.data.quantity
    groupBy:
      tenant_id: $.data.tenant_id""")

    meters_block = "\n\n".join(meter_lines) if meter_lines else ""

    return f"""\
# OpenMeter configuration for {slug}
# https://openmeter.io/docs/configuration

namespace: {slug}

ingestors:
  - name: http
    type: http
    config:
      addr: 0.0.0.0:8888
      path: /ingest

portal:
  enabled: true
  tokenExpiration: 1h

meters:
{meters_block}

sink:
  kafka:
    brokers:
      - kafka:9092
    topic: {slug}-metering-events
    partitions: 4

storage:
  postgres:
    url: ${{OPENMETER_POSTGRES_URL}}
"""


# ── CloudEvents schema ────────────────────────────────────────────────────────


def generate_metering_event_schema(
    entities: List[Dict[str, Any]], slug: str
) -> str:
    """
    CloudEvents JSON schema for metering events.
    Each entity gets a distinct event type: com.{slug}.{entity}.metered
    """
    event_types = []
    for ent in entities:
        table = ent.get("table", "resource")
        event_types.append(f"com.{slug}.{_snake(table)}.metered")

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://{slug}.aetheros.io/schemas/metering-event.json",
        "title": f"{slug} Metering CloudEvent",
        "description": "CloudEvents envelope for usage metering events",
        "type": "object",
        "required": ["specversion", "id", "source", "type", "data"],
        "properties": {
            "specversion": {"type": "string", "const": "1.0"},
            "id": {"type": "string", "format": "uuid"},
            "source": {
                "type": "string",
                "description": "Origin service URI",
                "example": f"https://api.{slug}.io",
            },
            "type": {
                "type": "string",
                "enum": event_types,
                "description": "Metering event type identifying the entity and action",
            },
            "time": {"type": "string", "format": "date-time"},
            "datacontenttype": {"type": "string", "const": "application/json"},
            "data": {
                "type": "object",
                "required": ["entity", "quantity", "unit", "tenant_id", "timestamp"],
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Domain entity name",
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Measured quantity (calls, GB, users, etc.)",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit of measurement",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Tenant or organisation identifier",
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time",
                        "description": "When the usage occurred",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional arbitrary key-value metadata",
                    },
                },
            },
        },
    }
    return json.dumps(schema, indent=2)


# ── Metering middleware ───────────────────────────────────────────────────────


def generate_metering_middleware(entities: List[Dict[str, Any]], slug: str) -> str:
    """
    Async FastAPI middleware that intercepts entity-endpoint requests and fires
    a CloudEvents metering event to OpenMeter via a background task (fire-and-forget).
    """
    # The generated backend mounts every entity router at /api/<table> (table name as is).
    prefixes = [f"/api/{_snake(e.get('table', 'resource'))}" for e in entities]
    prefixes_repr = repr(prefixes)

    return f'''\
"""
Usage metering middleware for {slug}.

Intercepts every successful API request to entity endpoints and posts a
CloudEvents metering event to OpenMeter asynchronously (fire-and-forget
via BackgroundTasks so latency impact is negligible).

Environment variables:
  OPENMETER_URL      — e.g. http://openmeter:8888
  OPENMETER_API_KEY  — optional bearer token for OpenMeter
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

OPENMETER_URL = os.getenv("OPENMETER_URL", "http://openmeter:8888")
OPENMETER_API_KEY = os.getenv("OPENMETER_API_KEY", "")
METERED_PREFIXES: list[str] = {prefixes_repr}


def _extract_entity(path: str) -> str | None:
    """Return the entity (table) name for /api/<table> and /api/<table>/..., else None."""
    for prefix in METERED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return prefix.rsplit("/", 1)[-1]
    return None


try:  # the generated backend's token verification (src/auth.py)
    from src.auth import ALGORITHM as _ALG, _PUBLIC_KEY, jwt as _jwt
except ImportError:
    try:
        from auth import ALGORITHM as _ALG, _PUBLIC_KEY, jwt as _jwt
    except ImportError:
        _jwt = None


def _get_tenant_id(request: Request) -> str:
    """Tenant from the VERIFIED access token (org_id claim). A client-supplied header is
    never trusted: anyone could bill usage to another tenant."""
    auth = request.headers.get("Authorization", "")
    if _jwt is None or not auth.startswith("Bearer "):
        return "unknown"
    try:
        claims = _jwt.decode(auth[7:], _PUBLIC_KEY, algorithms=[_ALG])
    except Exception as exc:
        logger.debug("metering_middleware: token not verified: %s", exc)
        return "unknown"
    return str(claims.get("org_id") or "unknown")


async def _post_metering_event(entity: str, tenant_id: str) -> None:
    """Fire a CloudEvents metering event to OpenMeter (background task)."""
    event = {{
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": f"https://api.{slug}.io",
        "type": f"com.{slug}.{{entity}}.metered",
        "time": datetime.now(timezone.utc).isoformat(),
        "datacontenttype": "application/json",
        "data": {{
            "entity": entity,
            "quantity": 1,
            "unit": "requests",
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }},
    }}
    headers = {{"Content-Type": "application/cloudevents+json"}}
    if OPENMETER_API_KEY:
        headers["Authorization"] = f"Bearer {{OPENMETER_API_KEY}}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{{OPENMETER_URL}}/ingest",
                json=event,
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.warning("metering_middleware: OpenMeter ingest error %s", resp.status_code)
    except Exception as exc:
        logger.warning("metering_middleware: failed to post event: %s", exc)


class MeteringMiddleware(BaseHTTPMiddleware):
    """Intercept entity API calls and emit usage events to OpenMeter."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Only meter successful mutating or read requests on entity paths
        entity = _extract_entity(request.url.path)
        if entity and 200 <= response.status_code < 300:
            tenant_id = _get_tenant_id(request)
            import asyncio
            asyncio.create_task(_post_metering_event(entity, tenant_id))
            logger.debug(
                "metering_middleware: entity=%s tenant=%s elapsed=%dms",
                entity, tenant_id, elapsed_ms,
            )

        return response
'''


# ── OpenMeter Helm values ─────────────────────────────────────────────────────


def generate_openmeter_helm_values(slug: str) -> str:
    """OpenMeter Helm chart values: PostgreSQL backend, Kafka sink, 2 replicas."""
    return f"""\
# Helm values for the OpenMeter chart
# helm repo add openmeter https://charts.openmeter.io
# helm install openmeter openmeter/openmeter -f openmeter-values.yaml

replicaCount: 2

image:
  repository: ghcr.io/openmeterio/openmeter
  pullPolicy: IfNotPresent

config:
  namespace: {slug}

  ingestors:
    - name: http
      type: http
      config:
        addr: 0.0.0.0:8888
        path: /ingest

  sink:
    kafka:
      brokers:
        - kafka:9092
      topic: {slug}-metering-events

  storage:
    postgres:
      url: "$(OPENMETER_POSTGRES_URL)"

env:
  - name: OPENMETER_POSTGRES_URL
    valueFrom:
      secretKeyRef:
        name: {slug}-openmeter-secrets
        key: postgres-url

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

service:
  type: ClusterIP
  port: 8888

kafka:
  enabled: true
  replicaCount: 1
  persistence:
    size: 8Gi

postgresql:
  enabled: true
  auth:
    database: openmeter
    existingSecret: {slug}-openmeter-secrets
    secretKeys:
      adminPasswordKey: postgres-password

podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9999"
"""


# ── Package orchestrator ──────────────────────────────────────────────────────


def generate_billing_package(
    entities: List[Dict[str, Any]], slug: str, output_dir: Path
) -> Path:
    """
    Write the complete billing/metering package under output_dir/billing/.

    Layout:
      billing/
        openmeter-config.yaml
        event-schema.json
        billing_webhook.py
        metering_middleware.py
        helm/openmeter-values.yaml
    """
    billing_dir = output_dir / "billing"
    helm_dir = billing_dir / "helm"
    billing_dir.mkdir(parents=True, exist_ok=True)
    helm_dir.mkdir(parents=True, exist_ok=True)

    (billing_dir / "openmeter-config.yaml").write_text(
        generate_openmeter_config(slug, entities)
    )
    (billing_dir / "event-schema.json").write_text(
        generate_metering_event_schema(entities, slug)
    )
    (billing_dir / "billing_webhook.py").write_text(
        generate_stripe_webhook_handler(slug)
    )
    (billing_dir / "metering_middleware.py").write_text(
        generate_metering_middleware(entities, slug)
    )
    (helm_dir / "openmeter-values.yaml").write_text(
        generate_openmeter_helm_values(slug)
    )

    logger.info(
        "p18_billing_metering: billing package written to %s (%d entities)",
        billing_dir,
        len(entities),
    )
    return billing_dir
