"""
AetherOS — Webhook delivery with HMAC-SHA256 signing; durable retry with backoff is in outbox.py.

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
from typing import Any, Dict, List, Optional, Tuple

from aether_os.core.encryption import decrypt
from aether_os.core.security.safe_http import resolve_public, safe_request

logger = logging.getLogger(__name__)

_DELIVERY_TIMEOUT = 10.0       # seconds per HTTP attempt; retries and backoff live in core/webhooks/outbox.py


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
        """ONE signed POST of `payload` to `url`. Returns True on 2xx. Retrying is the outbox's job (it survives a
        restart; an in-process sleep loop did not). Use `attempt()` when the caller needs to know if a retry can help."""
        return (await self.attempt(url, secret, event_type, payload, delivery_id))[0]

    async def attempt(
        self,
        url: str,
        secret: str,
        event_type: str,
        payload: Dict[str, Any],
        delivery_id: Optional[str] = None,
    ) -> Tuple[bool, bool, str]:
        """-> (delivered, retryable, error). Not retryable: no signing secret, or the address is not public (SSRF)."""
        if not secret:
            # An HMAC keyed with "" can be forged by anyone — an unsigned-in-effect
            # delivery is worse than none, so refuse rather than send.
            logger.error("[webhook] no signing secret for %s — delivery of %s refused", url, event_type)
            return False, False, "no signing secret"
        delivery_id = delivery_id or str(uuid.uuid4())
        body = json.dumps({
            "id": delivery_id,
            "event": event_type,
            "ts": time.time(),
            "payload": payload,
        }, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-AetherOS-Event": event_type,
            "X-AetherOS-Delivery": delivery_id,
            "X-AetherOS-Signature-256": f"sha256={self._sign(body, secret)}",
        }
        try:
            # Resolve, check every address, connect to the checked one (DNS rebinding, H-09)
            resp = await safe_request("POST", url, content=body, headers=headers, timeout=_DELIVERY_TIMEOUT)
        except ValueError as exc:
            logger.error("[webhook] SSRF block: %s → %s: %s", event_type, url, exc)
            return False, False, "address not allowed"
        except Exception as exc:
            logger.warning("[webhook] %s → %s failed: %s", event_type, url, exc)
            return False, True, type(exc).__name__
        if resp.status_code < 300:
            logger.info("[webhook] delivered %s → %s", event_type, url)
            return True, False, ""
        logger.warning("[webhook] %s → %s returned HTTP %s", event_type, url, resp.status_code)
        return False, True, f"HTTP {resp.status_code}"


_delivery = WebhookDelivery()


_tasks: set = set()


async def deliver_event(
    org_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    """Write one outbox row per active subscribed webhook of `org_id` (durable: it survives a restart and is retried
    with backoff by the outbox sweeper, then dead-lettered), and make the first attempt right away in the background."""
    webhooks = await _get_org_webhooks(org_id, event_type)
    if not webhooks:
        return
    from aether_os.core.webhooks import outbox
    delivery_id = str(uuid.uuid4())
    for wh in webhooks:
        try:
            row_id = await outbox.enqueue(org_id, wh["id"], event_type, delivery_id, payload)
        except Exception as exc:
            # Not stored: the event would be lost silently. Say so, and still try once in memory.
            logger.warning("[webhook] outbox write failed for %s (%s); one in-memory attempt only", event_type, exc)
            row_id = None
        # Keep a reference: the loop holds tasks weakly, so an unreferenced task can be garbage collected mid-flight.
        coro = outbox.attempt_row(row_id) if row_id else outbox.send_direct(wh, event_type, payload, delivery_id)
        task = asyncio.create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def _signing_secret(stored: Optional[str]) -> str:
    """Recover the HMAC key from webhooks.secret (Fernet-encrypted by the gateway).

    A value that does not decrypt (written under another key, or damaged) returns "" and send() refuses the
    delivery: it is never used as the key itself. Plaintext rows from before encryption were encrypted by the
    hash_legacy_plaintext_tokens migration.
    """
    if not stored:
        return ""
    try:
        return decrypt(stored)
    except ValueError as exc:
        logger.warning("webhook signing secret cannot be decrypted (re-create the webhook): %s", exc)
        return ""


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
                result.append({"id": w.id, "url": w.url, "secret": _signing_secret(w.secret)})
        return result
    except Exception as exc:
        logger.debug("[webhook] fetch failed: %s", exc)
        return []
