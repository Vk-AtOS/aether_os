"""
AetherOS — Webhook delivery with HMAC-SHA256 signing and exponential-backoff retry.

Usage (from pipeline event emitters):
    from aether_os.core.webhooks.delivery import deliver_event
    await deliver_event(org_id="abc", event_type="pipeline.complete", payload={...})
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from aether_os.core.encryption import decrypt
from aether_os.core.security.safe_http import resolve_public, safe_request

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [5, 30, 120]   # seconds between attempts (exponential-ish)
_DELIVERY_TIMEOUT = 10.0       # seconds per HTTP attempt


def _assert_safe_url(url: str) -> None:
    """Raise ValueError unless every address `url` resolves to is public.

    Kept for callers that only check; sending must use safe_request, which also pins
    the connection to the checked address (a check followed by a fresh lookup can
    be defeated by DNS rebinding).
    """
    resolve_public(url)


class WebhookDelivery:
    """Stateless delivery helper — no instance state, safe to share."""

    def _sign(self, payload_bytes: bytes, secret: str) -> str:
        """Return HMAC-SHA256 hex digest of payload_bytes."""
        return hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

    async def send(
        self,
        url: str,
        secret: str,
        event_type: str,
        payload: Dict[str, Any],
        delivery_id: Optional[str] = None,
    ) -> bool:
        """
        POST `payload` to `url` with HMAC-SHA256 signature header.
        Retries up to _MAX_RETRIES times on network errors or 5xx responses.

        Returns True on success (2xx), False if all attempts failed.
        """
        if not secret:
            # An HMAC keyed with "" can be forged by anyone — an unsigned-in-effect
            # delivery is worse than none, so refuse rather than send.
            logger.error("[webhook] no signing secret for %s — delivery of %s refused", url, event_type)
            return False
        delivery_id = delivery_id or str(uuid.uuid4())
        body = json.dumps({
            "id": delivery_id,
            "event": event_type,
            "ts": time.time(),
            "payload": payload,
        }, separators=(",", ":")).encode()

        sig = self._sign(body, secret)
        headers = {
            "Content-Type": "application/json",
            "X-AetherOS-Event": event_type,
            "X-AetherOS-Delivery": delivery_id,
            "X-AetherOS-Signature-256": f"sha256={sig}",
        }

        for attempt in range(_MAX_RETRIES):
            try:
                # Resolve, check every address, connect to the checked one (DNS rebinding, H-09)
                resp = await safe_request("POST", url, content=body, headers=headers,
                                          timeout=_DELIVERY_TIMEOUT)
                if resp.status_code < 300:
                    logger.info("[webhook] delivered %s → %s (attempt %d)", event_type, url, attempt + 1)
                    return True
                logger.warning(
                    "[webhook] %s → %s returned HTTP %s (attempt %d/%d)",
                    event_type, url, resp.status_code, attempt + 1, _MAX_RETRIES,
                )
            except ValueError as exc:
                # SSRF check failed — abort all retries immediately
                logger.error("[webhook] SSRF block: %s → %s: %s", event_type, url, exc)
                return False
            except Exception as exc:
                logger.warning(
                    "[webhook] %s → %s failed: %s (attempt %d/%d)",
                    event_type, url, exc, attempt + 1, _MAX_RETRIES,
                )

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAYS[attempt])

        logger.error("[webhook] all %d attempts failed for %s → %s", _MAX_RETRIES, event_type, url)
        return False


_delivery = WebhookDelivery()


_tasks: set = set()
_MAX_CONCURRENT = 50
_slots: Optional[asyncio.Semaphore] = None


async def _bounded_send(**kw: Any) -> bool:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(_MAX_CONCURRENT)
    async with _slots:
        return await _delivery.send(**kw)


async def deliver_event(
    org_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    """
    Fetch all active webhooks for `org_id` subscribed to `event_type` and
    deliver asynchronously (fire-and-forget background tasks).
    """
    webhooks = await _get_org_webhooks(org_id, event_type)
    if not webhooks:
        return

    delivery_id = str(uuid.uuid4())
    for wh in webhooks:
        # Keep a reference: the loop holds tasks weakly, so an unreferenced delivery can be garbage collected mid-retry
        # (and the event is lost without a log line). The semaphore bounds how many deliveries run at once.
        task = asyncio.create_task(
            _bounded_send(
                url=wh["url"],
                secret=wh["secret"],
                event_type=event_type,
                payload=payload,
                delivery_id=delivery_id,
            )
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def _signing_secret(stored: Optional[str]) -> str:
    """Recover the HMAC key from webhooks.secret (Fernet-encrypted by the gateway).

    Rows created while only a bcrypt hash was kept have no recoverable key and
    return "" (send() refuses those — the webhook must be re-created). Rows older
    than that hold the plaintext secret, which is used as-is.
    """
    if not stored:
        return ""
    try:
        return decrypt(stored)
    except ValueError:
        return stored


async def _get_org_webhooks(org_id: str, event_type: str) -> List[Dict[str, Any]]:
    """Return active webhooks for org that are subscribed to event_type."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Webhook
        from sqlalchemy import select

        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(Webhook).where(
                    Webhook.org_id == org_id,
                    Webhook.is_active == True,  # noqa: E712
                )
            )).scalars().all()

        result = []
        for w in rows:
            subscribed = w.events or []
            if not subscribed or event_type in subscribed or "*" in subscribed:
                result.append({"url": w.url, "secret": _signing_secret(w.secret)})
        return result
    except Exception as exc:
        logger.debug("[webhook] fetch failed: %s", exc)
        return []
