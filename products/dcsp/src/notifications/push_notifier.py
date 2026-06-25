from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

FIREBASE_SERVER_KEY = os.getenv(
    "FIREBASE_SERVER_KEY", "")
FIREBASE_PROJECT_ID = os.getenv(
    "FIREBASE_PROJECT_ID", "")
NOTIFICATIONS_ENABLED = bool(
    os.getenv("NOTIFICATIONS_ENABLED", ""))

# In-memory notification log
_NOTIFICATION_LOG: list[dict] = []
# In-memory device tokens
_DEVICE_TOKENS: dict[str, dict] = {}
# {token: {user, platform, registered_at}}


@dataclass
class NotificationPayload:
    title: str
    body: str
    data: dict = field(
        default_factory=dict)
    priority: str = "normal"
    # "normal" or "high"
    topic: Optional[str] = None


@dataclass
class NotificationResult:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    recipients: int = 0


def is_notifications_enabled() -> bool:
    return bool(
        FIREBASE_SERVER_KEY and
        NOTIFICATIONS_ENABLED
    )


def register_device_token(
    token: str,
    user: str,
    platform: str = "web"
    # "web", "ios", "android"
) -> bool:
    """Register a device push token."""
    if not token or not user:
        return False
    _DEVICE_TOKENS[token] = {
        "token": token,
        "user": user,
        "platform": platform,
        "registered_at":
            datetime.utcnow().isoformat()
    }
    logger.info(
        f"Registered device token for "
        f"{user} ({platform})")
    return True


def unregister_device_token(
    token: str
) -> bool:
    """Remove a device token."""
    if token in _DEVICE_TOKENS:
        del _DEVICE_TOKENS[token]
        return True
    return False


def get_tokens_for_user(
    user: str
) -> list[str]:
    return [
        t for t, d in
        _DEVICE_TOKENS.items()
        if d.get("user") == user
    ]


def list_device_tokens() -> list[dict]:
    return list(_DEVICE_TOKENS.values())


def _log_notification(
    payload: NotificationPayload,
    result: NotificationResult
) -> None:
    _NOTIFICATION_LOG.append({
        "title": payload.title,
        "body": payload.body,
        "priority": payload.priority,
        "success": result.success,
        "recipients": result.recipients,
        "sent_at": datetime.utcnow().isoformat(),
        "skipped": result.skipped
    })


def send_notification(
    payload: NotificationPayload,
    tokens: Optional[list[str]] = None
) -> NotificationResult:
    """
    Send a push notification.
    If tokens is None, sends to all registered.
    Gracefully skips if not configured.
    """
    if not is_notifications_enabled():
        result = NotificationResult(
            success=False,
            skipped=True,
            skip_reason=(
                "Notifications not enabled")
        )
        _log_notification(payload, result)
        return result

    target_tokens = tokens or list(
        _DEVICE_TOKENS.keys())

    if not target_tokens:
        result = NotificationResult(
            success=False,
            skipped=True,
            skip_reason="No device tokens"
        )
        _log_notification(payload, result)
        return result

    # Attempt real Firebase send
    try:
        import requests
        fcm_payload = {
            "registration_ids": target_tokens,
            "notification": {
                "title": payload.title,
                "body": payload.body
            },
            "data": payload.data,
            "priority": payload.priority
        }
        resp = requests.post(
            "https://fcm.googleapis.com"
            "/fcm/send",
            json=fcm_payload,
            headers={
                "Authorization":
                    f"key="
                    f"{FIREBASE_SERVER_KEY}",
                "Content-Type":
                    "application/json"
            },
            timeout=5
        )
        if resp.status_code == 200:
            result = NotificationResult(
                success=True,
                message_id=str(
                    resp.json().get(
                        "multicast_id", "")),
                recipients=len(target_tokens)
            )
        else:
            result = NotificationResult(
                success=False,
                error=(
                    f"FCM returned "
                    f"{resp.status_code}"),
                recipients=0
            )
    except Exception as e:
        result = NotificationResult(
            success=False,
            error=str(e),
            recipients=0
        )

    _log_notification(payload, result)
    return result


def notify_escalation(
    job_id: str,
    repo_name: str,
    error_type: str
) -> NotificationResult:
    """Send escalation notification."""
    payload = NotificationPayload(
        title="DCSP: Repair Escalated",
        body=(
            f"{repo_name}: {error_type} "
            f"requires manual intervention"
        ),
        data={
            "job_id": job_id,
            "type": "escalation"
        },
        priority="high"
    )
    return send_notification(payload)


def notify_critical_failure(
    repo_name: str,
    error_type: str,
    incident_id: Optional[str] = None
) -> NotificationResult:
    """Send critical failure notification."""
    payload = NotificationPayload(
        title="DCSP: Critical Failure",
        body=(
            f"{repo_name}: {error_type} "
            f"is recurring critically"
        ),
        data={
            "incident_id": incident_id or "",
            "type": "critical_failure"
        },
        priority="high"
    )
    return send_notification(payload)


def get_notification_log(
    limit: int = 50
) -> list[dict]:
    return _NOTIFICATION_LOG[-limit:]


def clear_notification_log() -> None:
    _NOTIFICATION_LOG.clear()
