from __future__ import annotations
import pytest
import json
import hmac
import hashlib
from src.integrations.github_app import (
    verify_webhook_signature,
    parse_webhook_event,
    handle_installation_event,
    list_installations,
    get_installation,
    generate_oauth_state,
    validate_oauth_state,
    get_oauth_authorize_url,
    GitHubWebhookEvent,
    _INSTALLATIONS,
    _OAUTH_STATES
)

@pytest.fixture(autouse=True)
def clear_state():
    _INSTALLATIONS.clear()
    _OAUTH_STATES.clear()
    yield
    _INSTALLATIONS.clear()
    _OAUTH_STATES.clear()

def test_verify_signature_no_secret():
    """No secret = always valid (dev mode)."""
    import src.integrations.github_app as ga
    original = ga.GITHUB_APP_SECRET
    ga.GITHUB_APP_SECRET = ""  # simulate no secret set
    try:
        result = verify_webhook_signature(
            b"payload", None)
        assert result is True
    finally:
        ga.GITHUB_APP_SECRET = original

def test_verify_signature_missing_header():
    import src.integrations.github_app as ga
    original = ga.GITHUB_APP_SECRET
    ga.GITHUB_APP_SECRET = "mysecret"
    try:
        result = verify_webhook_signature(
            b"payload", None)
        assert result is False
    finally:
        ga.GITHUB_APP_SECRET = original

def test_verify_signature_valid():
    import src.integrations.github_app as ga
    secret = "testsecret"
    payload = b"test payload"
    sig = "sha256=" + hmac.new(
        secret.encode(), payload,
        hashlib.sha256).hexdigest()
    original = ga.GITHUB_APP_SECRET
    ga.GITHUB_APP_SECRET = secret
    try:
        result = verify_webhook_signature(
            payload, sig)
        assert result is True
    finally:
        ga.GITHUB_APP_SECRET = original

def test_parse_webhook_event():
    payload = {
        "action": "created",
        "installation": {"id": 123},
        "repository": {
            "full_name": "acme/billing"},
        "sender": {"login": "alice"}
    }
    event = parse_webhook_event(
        "installation", payload)
    assert event.event_type == "installation"
    assert event.action == "created"
    assert event.installation_id == "123"
    assert event.repo_full_name == \
        "acme/billing"
    assert event.sender_login == "alice"

def test_handle_installation_created():
    payload = {
        "action": "created",
        "installation": {
            "id": 456,
            "account": {
                "login": "acme",
                "type": "Organization"
            }
        },
        "repositories": [
            {"full_name": "acme/api"},
            {"full_name": "acme/web"}
        ],
        "sender": {"login": "alice"}
    }
    event = parse_webhook_event(
        "installation", payload)
    result = handle_installation_event(event)
    assert result["status"] == "installed"
    assert get_installation("456") is not None
    inst = get_installation("456")
    assert inst["account_login"] == "acme"
    assert "acme/api" in inst["repos"]

def test_handle_installation_deleted():
    # First create it
    payload_create = {
        "action": "created",
        "installation": {
            "id": 789,
            "account": {
                "login": "bob",
                "type": "User"
            }
        },
        "repositories": [],
        "sender": {"login": "bob"}
    }
    event = parse_webhook_event(
        "installation", payload_create)
    handle_installation_event(event)

    # Now delete it
    payload_delete = {
        "action": "deleted",
        "installation": {"id": 789},
        "sender": {"login": "bob"}
    }
    event2 = parse_webhook_event(
        "installation", payload_delete)
    result = handle_installation_event(event2)
    assert result["status"] == "uninstalled"
    assert not get_installation(
        "789")["is_active"]

def test_list_installations_empty():
    result = list_installations()
    assert result == []

def test_list_installations_active_only():
    _INSTALLATIONS["a1"] = {
        "installation_id": "a1",
        "is_active": True,
        "account_login": "acme"
    }
    _INSTALLATIONS["a2"] = {
        "installation_id": "a2",
        "is_active": False,
        "account_login": "bob"
    }
    result = list_installations()
    assert len(result) == 1
    assert result[0]["installation_id"] == "a1"

def test_generate_oauth_state():
    state = generate_oauth_state(
        "/dashboard/github")
    assert isinstance(state, str)
    assert len(state) > 10
    assert state in _OAUTH_STATES

def test_validate_oauth_state_valid():
    state = generate_oauth_state()
    result = validate_oauth_state(state)
    assert result is True
    # consumed - should be gone
    assert state not in _OAUTH_STATES

def test_validate_oauth_state_invalid():
    result = validate_oauth_state(
        "nonexistent_state")
    assert result is False

def test_get_oauth_url_no_client_id():
    url = get_oauth_authorize_url("state123")
    assert url == ""

def test_webhook_api_no_secret():
    import src.integrations.github_app as ga
    from fastapi.testclient import TestClient
    from src.api.main import app
    original = ga.GITHUB_APP_SECRET
    ga.GITHUB_APP_SECRET = ""  # simulate no secret configured
    try:
        client = TestClient(app)
        payload = json.dumps({
            "action": "ping",
            "installation": {},
            "sender": {"login": "github"}
        }).encode()
        r = client.post(
            "/github/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json"
            }
        )
        assert r.status_code == 200
    finally:
        ga.GITHUB_APP_SECRET = original

def test_github_status_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "gh_status_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/github/status",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "configured" in data
    assert "installations" in data

def test_installations_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "gh_inst_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/github/installations",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "installations" in data

def test_github_dashboard_page():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "gh_dash_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/dashboard/github",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert "GitHub" in r.text
