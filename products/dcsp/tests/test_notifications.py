from __future__ import annotations
import pytest
from src.notifications.push_notifier import (
    register_device_token,
    unregister_device_token,
    get_tokens_for_user,
    list_device_tokens,
    send_notification,
    notify_escalation,
    notify_critical_failure,
    get_notification_log,
    clear_notification_log,
    is_notifications_enabled,
    NotificationPayload,
    NotificationResult,
    _DEVICE_TOKENS,
    _NOTIFICATION_LOG
)

@pytest.fixture(autouse=True)
def clear_state():
    _DEVICE_TOKENS.clear()
    _NOTIFICATION_LOG.clear()
    yield
    _DEVICE_TOKENS.clear()
    _NOTIFICATION_LOG.clear()

def test_notifications_disabled_by_default():
    assert is_notifications_enabled() \
        is False

def test_register_device_token():
    ok = register_device_token(
        "tok_abc", "alice", "web")
    assert ok is True
    assert "tok_abc" in _DEVICE_TOKENS

def test_register_empty_token():
    ok = register_device_token("", "alice")
    assert ok is False

def test_unregister_token():
    register_device_token(
        "tok_del", "bob", "ios")
    ok = unregister_device_token("tok_del")
    assert ok is True
    assert "tok_del" not in _DEVICE_TOKENS

def test_unregister_nonexistent():
    ok = unregister_device_token("fake_tok")
    assert ok is False

def test_get_tokens_for_user():
    register_device_token(
        "tok1", "alice", "web")
    register_device_token(
        "tok2", "alice", "ios")
    register_device_token(
        "tok3", "bob", "web")
    tokens = get_tokens_for_user("alice")
    assert "tok1" in tokens
    assert "tok2" in tokens
    assert "tok3" not in tokens

def test_send_notification_skipped():
    """Without config, send is skipped."""
    payload = NotificationPayload(
        title="Test",
        body="Test notification"
    )
    result = send_notification(payload)
    assert result.skipped is True
    assert result.success is False

def test_send_notification_logged():
    """Skipped notifications are still logged."""
    payload = NotificationPayload(
        title="Alert",
        body="Something happened"
    )
    send_notification(payload)
    log = get_notification_log()
    assert len(log) == 1
    assert log[0]["title"] == "Alert"

def test_notify_escalation_skipped():
    result = notify_escalation(
        "job_123", "acme/api",
        "AttributeError")
    assert result.skipped is True
    log = get_notification_log()
    assert len(log) == 1
    assert "Escalated" in log[0]["title"]

def test_notify_critical_failure_skipped():
    result = notify_critical_failure(
        "acme/billing", "TypeError",
        "inc_456")
    assert result.skipped is True

def test_notification_payload_defaults():
    p = NotificationPayload(
        title="T", body="B")
    assert p.priority == "normal"
    assert p.data == {}
    assert p.topic is None

def test_notification_result_defaults():
    r = NotificationResult(success=True)
    assert r.recipients == 0
    assert r.skipped is False

def test_clear_notification_log():
    send_notification(NotificationPayload(
        title="T", body="B"))
    clear_notification_log()
    assert get_notification_log() == []

def test_notification_status_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "notif_status_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/notifications/status",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "device_count" in data

def test_register_device_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "notif_reg_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.post(
        "/api/notifications/register",
        json={
            "token": "device_xyz",
            "platform": "web"
        },
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert r.json()["registered"] is True

def test_pwa_manifest():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    r = client.get("/manifest.json")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == \
        "DCSP - Code Self-healing"
    assert data["short_name"] == "DCSP"
    assert "icons" in data
    assert data["display"] == "standalone"

def test_service_worker():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "CACHE_NAME" in r.text
    assert "push" in r.text
