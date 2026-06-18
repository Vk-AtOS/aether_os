"""
AetherOS — Webhooks Router
GET /webhooks
POST /webhooks
DELETE /webhooks/{webhook_id}
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def _current_user():
    return Depends(get_current_user)


@router.get("/webhooks")
async def list_webhooks(user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Webhook
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(Webhook).where(Webhook.org_id == org_id)
        )).scalars().all()
    return [
        {
            "id": w.id,
            "url": w.url,
            "events": w.events,
            "is_active": w.is_active,
            "created_at": str(w.created_at),
        }
        for w in rows
    ]


@router.post("/webhooks")
async def create_webhook(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    import secrets as _secrets
    import ipaddress as _ip
    import urllib.parse as _urlparse
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Webhook

    url = req.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url is required")

    # T2-11: SSRF allowlist — block private/internal networks and metadata endpoints
    try:
        _parsed = _urlparse.urlparse(url)
        if _parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=422, detail="Webhook URL must use http or https")
        _host = _parsed.hostname or ""
        _blocked_hosts = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if _host in _blocked_hosts:
            raise HTTPException(status_code=422, detail="Webhook URL targets a blocked host")
        try:
            _addr = _ip.ip_address(_host)
            if _addr.is_private or _addr.is_loopback or _addr.is_link_local or _addr.is_reserved:
                raise HTTPException(status_code=422, detail="Webhook URL must not target a private or reserved IP")
        except ValueError as e:
            logger.warning("webhooks_router: %r is not a raw IP (hostname, DNS resolves at delivery time): %s", _host, e)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid webhook URL")

    events = req.get("events", [])
    secret = _secrets.token_hex(32)
    org_id = user["org_id"]

    sf = get_session_factory()
    async with sf() as session:
        new_webhook = Webhook(
            url=url,
            events=events,
            secret=secret,
            org_id=org_id,
        )
        session.add(new_webhook)
        await session.commit()
        await session.refresh(new_webhook)

    return {"id": new_webhook.id, "url": new_webhook.url, "is_active": True}


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Webhook
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        wh = (await session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await session.delete(wh)
        await session.commit()
    return {"success": True}
