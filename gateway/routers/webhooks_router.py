"""
AetherOS — Webhooks Router
GET /webhooks
POST /webhooks
DELETE /webhooks/{webhook_id}
"""
from __future__ import annotations
import logging
from typing import Any, Dict
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.db import get_session_factory
from aether_os.core.encryption import encrypt
from aether_os.core.models import Webhook
from sqlalchemy import select
import httpx
import json
import secrets as _secrets
import time
from aether_os.core.security.safe_http import UnsafeURL, check_url_shape, safe_request
from aether_os.core.webhooks.delivery import _delivery, _signing_secret
logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def _check_url_or_422(url: str) -> None:
    """Reject URLs that could reach internal networks (SSRF). DNS is checked at send time."""
    try:
        check_url_shape(url)
    except UnsafeURL as exc:
        raise HTTPException(status_code=422, detail=f"Webhook URL refused: {exc}") from exc


def _current_user():
    return Depends(get_current_user)
@router.get("/webhooks")
async def list_webhooks(user: Dict[str, Any] = _current_user()):
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
    url = req.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url is required")
    _check_url_or_422(url)
    events = req.get("events", [])
    # M3: generate raw secret, return it ONCE. HMAC signing needs the key itself, so it
    # is stored Fernet-encrypted (AETHER_FIELD_KEY); with only the bcrypt hash kept,
    # every delivery was signed with an empty key.
    secret = _secrets.token_hex(32)
    secret_hash = bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        new_webhook = Webhook(
            url=url,
            events=events,
            secret=encrypt(secret),  # ciphertext, never plaintext
            secret_hash=secret_hash,
            org_id=org_id,
        )
        session.add(new_webhook)
        await session.commit()
        await session.refresh(new_webhook)
    # Return the raw secret exactly once — caller must persist it; it cannot be recovered
    return {"id": new_webhook.id, "url": new_webhook.url, "is_active": True, "secret": secret}
@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, user: Dict[str, Any] = _current_user()):
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
@router.put("/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    org_id = user["org_id"]
    url = req.get("url", "").strip()
    events = req.get("events")
    sf = get_session_factory()
    async with sf() as session:
        wh = (await session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Webhook not found")
        if url:
            _check_url_or_422(url)
            wh.url = url
        if events is not None:
            wh.events = events
        await session.commit()
        await session.refresh(wh)
    return {"id": wh.id, "url": wh.url, "events": wh.events, "is_active": wh.is_active}
@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, user: Dict[str, Any] = _current_user()):
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        wh = (await session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Webhook not found")
    # Same signed, SSRF-checked, address-pinned sender as real deliveries.
    secret = _signing_secret(wh.secret)
    if not secret:
        return {"ok": False, "status_code": None,
                "message": "This webhook has no recoverable signing secret; re-create it."}
    body = json.dumps({"event": "webhook.test", "timestamp": time.time(),
                       "message": "AetherOS test ping"}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-AetherOS-Event": "webhook.test",
               "X-AetherOS-Signature-256": f"sha256={_delivery._sign(body, secret)}"}
    try:
        resp = await safe_request("POST", wh.url, content=body, headers=headers, timeout=10)
    except UnsafeURL as exc:
        return {"ok": False, "status_code": None, "message": f"Refused: {exc}"}
    except httpx.HTTPError as exc:
        logger.warning("webhook test %s failed: %s", webhook_id, exc)
        return {"ok": False, "status_code": None, "message": "Could not reach the endpoint"}
    return {"ok": resp.status_code < 400, "status_code": resp.status_code, "message": f"HTTP {resp.status_code}"}
