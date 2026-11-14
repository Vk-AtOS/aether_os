"""
Service Catalog Generator — AetherOS Layer 7 / p19.

Generates the backend FastAPI router and SQLAlchemy models that power the
cloud console's API endpoints:
  GET  /api/platform/stats
  GET  /api/platform/events
  GET  /api/services
  POST /api/services/{name}/launch
  GET  /api/resources/{id}/status
  GET  /api/billing/current
  GET  /api/billing/invoice/current

Also writes migration.sql for the two new tables (service_instances,
platform_events) so a fresh DB can be set up without Alembic.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


def generate_catalog_models(slug: str) -> str:
    return f'''\
"""SQLAlchemy models for the {slug} service catalog (Layer 7)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InstanceStatus(str, PyEnum):
    provisioning = "provisioning"
    running = "running"
    stopped = "stopped"
    error = "error"


class ServiceInstance(Base):
    """A single provisioned instance of a catalog service."""
    __tablename__ = "service_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name = Column(String(128), nullable=False)
    status = Column(Enum(InstanceStatus), default=InstanceStatus.provisioning, nullable=False)
    config_json = Column(Text, default="{{}}")
    tenant_id = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class PlatformEvent(Base):
    """Audit trail of platform actions (launches, stops, deletes)."""
    __tablename__ = "platform_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    tenant_id = Column(String(128), nullable=False)
    payload_json = Column(Text, default="{{}}")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
'''


def generate_catalog_migration(slug: str) -> str:
    return f"""\
-- Layer 7 migration: service_instances + platform_events for {slug}
-- Run once against a fresh or existing database.

CREATE TYPE instance_status AS ENUM ('provisioning', 'running', 'stopped', 'error');

CREATE TABLE IF NOT EXISTS service_instances (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name VARCHAR(128) NOT NULL,
    status      instance_status NOT NULL DEFAULT 'provisioning',
    config_json TEXT NOT NULL DEFAULT '{{}}',
    tenant_id   VARCHAR(128) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128),
    tenant_id   VARCHAR(128) NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{{}}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_instances_tenant ON service_instances(tenant_id);
CREATE INDEX IF NOT EXISTS idx_platform_events_tenant ON platform_events(tenant_id, created_at DESC);
"""


def generate_catalog_api(entities: List[Dict], slug: str, backend_lang: str) -> str:
    entity_names = [e.get("table", e.get("name", "resource")) for e in entities]
    service_list = ", ".join(f'"{n}"' for n in entity_names)
    return f'''\
"""
FastAPI service catalog router for {slug} — Layer 7 / p19.

Mounts at /api — attach to the main FastAPI app with:
    app.include_router(catalog_router, prefix="")

All tenant endpoints require a valid signed Bearer token (tenant_id = org_id or sub).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

catalog_router = APIRouter(tags=["service-catalog"])

KNOWN_SERVICES: List[str] = [{service_list}]


try:  # the generated backend's token verification (src/auth.py)
    from src.auth import ALGORITHM as _ALG, _PUBLIC_KEY, jwt as _jwt
except ImportError:
    try:
        from auth import ALGORITHM as _ALG, _PUBLIC_KEY, jwt as _jwt
    except ImportError:
        _jwt = None


def _get_tenant(request: Request) -> str:
    """Tenant of the caller, from a signature-verified access token (org_id, else sub).

    Fails closed: no token, an invalid token, or a backend without src.auth is an
    error, never a shared 'default' tenant.
    """
    if _jwt is None:
        raise HTTPException(status_code=503, detail="service catalog disabled: src.auth not found")
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = _jwt.decode(token, _PUBLIC_KEY, algorithms=[_ALG])
    except Exception as e:
        logger.warning("catalog: token rejected: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e
    tenant = claims.get("org_id") or claims.get("sub")
    if not tenant or claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    return str(tenant)


async def _get_db(request: Request) -> AsyncSession:
    """Yield an AsyncSession from the app\'s db factory (set at startup)."""
    async_session_factory = request.app.state.db_session
    async with async_session_factory() as session:
        yield session


@catalog_router.get("/api/platform/stats")
async def platform_stats(
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Aggregate resource counts, active services, and a synthetic health score."""
    tenant_id = _get_tenant(request)
    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN status=\'running\' THEN 1 ELSE 0 END) AS running "
                "FROM service_instances WHERE tenant_id = :tid"
            ),
            {{"tid": tenant_id}},
        )
        row = result.fetchone()
        total = int(row.total or 0)
        running = int(row.running or 0)
        health = round(running / total * 100) if total else 100
        return {{
            "total_resources": total,
            "monthly_spend": round(total * 0.12, 2),
            "active_services": len(KNOWN_SERVICES),
            "health_score": health,
            "resource_counts": {{svc: 0 for svc in KNOWN_SERVICES}},
        }}
    except Exception as e:
        logger.warning("catalog: platform_stats DB error: %s", e)
        return {{
            "total_resources": 0, "monthly_spend": 0.0,
            "active_services": len(KNOWN_SERVICES), "health_score": 100,
            "resource_counts": {{svc: 0 for svc in KNOWN_SERVICES}},
        }}


@catalog_router.get("/api/platform/events")
async def platform_events(
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Last 20 audit events for this tenant."""
    tenant_id = _get_tenant(request)
    try:
        result = await db.execute(
            text(
                "SELECT id, event_type, resource_id, created_at FROM platform_events "
                "WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 20"
            ),
            {{"tid": tenant_id}},
        )
        rows = result.fetchall()
        return {{
            "events": [
                {{"id": str(r.id), "event_type": r.event_type,
                  "resource_id": r.resource_id,
                  "created_at": r.created_at.isoformat()}}
                for r in rows
            ]
        }}
    except Exception as e:
        logger.warning("catalog: platform_events DB error: %s", e)
        return {{"events": []}}


@catalog_router.get("/api/services")
async def list_services() -> List[Dict[str, Any]]:
    """Return available services with GA status."""
    return [
        {{"name": svc, "status": "GA", "description": f"Manage {{svc}} resources"}}
        for svc in KNOWN_SERVICES
    ]


@catalog_router.post("/api/services/{{service_name}}/launch")
async def launch_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Provision a new service instance and log a platform event."""
    if service_name not in KNOWN_SERVICES:
        raise HTTPException(status_code=404, detail=f"Service {{service_name}} not found")

    tenant_id = _get_tenant(request)
    body = {{}}
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("catalog: launch body parse failed: %s", e)

    instance_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text(
                "INSERT INTO service_instances (id, service_name, status, config_json, tenant_id, created_at, updated_at) "
                "VALUES (:id, :svc, \'provisioning\', :cfg, :tid, :now, :now)"
            ),
            {{
                "id": instance_id, "svc": service_name,
                "cfg": json.dumps(body), "tid": tenant_id, "now": now,
            }},
        )
        await db.execute(
            text(
                "INSERT INTO platform_events (id, event_type, resource_id, tenant_id, payload_json, created_at) "
                "VALUES (:id, :evt, :rid, :tid, :payload, :now)"
            ),
            {{
                "id": str(uuid.uuid4()), "evt": "launch",
                "rid": instance_id, "tid": tenant_id,
                "payload": json.dumps({{"service": service_name, "config": body}}),
                "now": now,
            }},
        )
        await db.commit()
    except Exception as e:
        logger.error("catalog: launch DB write failed: %s", e)
        await db.rollback()
        raise HTTPException(status_code=503, detail="Could not record the launch; nothing was provisioned") from e

    return {{"id": instance_id, "status": "provisioning", "service_name": service_name}}


@catalog_router.get("/api/resources/{{resource_id}}/status")
async def resource_status(
    resource_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Return current status of a provisioned resource."""
    tenant_id = _get_tenant(request)
    try:
        result = await db.execute(
            text(
                "SELECT id, service_name, status, created_at, updated_at "
                "FROM service_instances WHERE id = :rid AND tenant_id = :tid"
            ),
            {{"rid": resource_id, "tid": tenant_id}},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Resource not found")
        return {{
            "id": str(row.id), "service_name": row.service_name,
            "status": row.status, "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(), "metadata": {{}},
        }}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("catalog: resource_status DB error: %s", e)
        return {{"id": resource_id, "status": "unknown", "metadata": {{}}}}


@catalog_router.get("/api/billing/current")
async def billing_current(
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Return current-month spend estimate and per-service breakdown."""
    tenant_id = _get_tenant(request)
    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")

    try:
        result = await db.execute(
            text(
                "SELECT service_name, COUNT(*) AS cnt "
                "FROM service_instances WHERE tenant_id = :tid "
                "GROUP BY service_name"
            ),
            {{"tid": tenant_id}},
        )
        rows = result.fetchall()
        breakdown = [
            {{"service": r.service_name, "resource_count": int(r.cnt), "cost": round(int(r.cnt) * 0.12, 2)}}
            for r in rows
        ]
        total = sum(b["cost"] for b in breakdown)
        return {{"month": month_str, "total_usd": round(total, 2), "breakdown": breakdown, "daily_spend": []}}
    except Exception as e:
        logger.warning("catalog: billing_current DB error: %s", e)
        return {{"month": month_str, "total_usd": 0.0, "breakdown": [], "daily_spend": []}}


@catalog_router.get("/api/billing/invoice/current")
async def billing_invoice(
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> JSONResponse:
    """Return a JSON invoice for the current month (downloadable)."""
    data = await billing_current(request, db)
    now = datetime.now(timezone.utc)
    invoice = {{
        "invoice_id": str(uuid.uuid4()),
        "tenant_id": _get_tenant(request),
        "period": data["month"],
        "generated_at": now.isoformat(),
        "line_items": data["breakdown"],
        "total_usd": data["total_usd"],
    }}
    return JSONResponse(
        content=invoice,
        headers={{"Content-Disposition": f\'attachment; filename="invoice-{{data["month"]}}.json"\'}}
    )
'''


def generate_catalog_package(
    entities: List[Dict],
    slug: str,
    output_dir: Path,
    backend_lang: str,
) -> Path:
    """Write router.py, models.py, migration.sql to output_dir/service_catalog/."""
    catalog_dir = output_dir / "service_catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)

    (catalog_dir / "router.py").write_text(generate_catalog_api(entities, slug, backend_lang))
    (catalog_dir / "models.py").write_text(generate_catalog_models(slug))
    (catalog_dir / "migration.sql").write_text(generate_catalog_migration(slug))

    logger.info(
        "catalog_generator: wrote service_catalog/ to %s (%d entity types)",
        catalog_dir, len(entities),
    )
    return catalog_dir
