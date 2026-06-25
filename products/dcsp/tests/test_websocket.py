from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS

client = TestClient(app)

import pytest
from starlette.websockets import WebSocketDisconnect

def test_websocket_rejects_unauthenticated():
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/dashboard") as ws:
            pass
    assert exc.value.code == 4001

def test_websocket_rejects_invalid_token():
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/dashboard?token=invalid") as ws:
            pass
    assert exc.value.code == 4001

def test_websocket_accepts_valid_token():
    token = "ws_test_token"
    ACTIVE_SESSIONS[token] = "admin"
    with client.websocket_connect(
        f"/ws/dashboard?token={token}") as ws:
        # Should receive init message
        import json
        data = json.loads(ws.receive_text())
        assert data["type"] == "init"
        assert "jobs" in data

def test_websocket_responds_to_ping():
    token = "ws_ping_token"
    ACTIVE_SESSIONS[token] = "admin"
    with client.websocket_connect(
        f"/ws/dashboard?token={token}") as ws:
        import json
        # Skip init message
        ws.receive_text()
        # Send ping
        ws.send_text("ping")
        resp = json.loads(ws.receive_text())
        assert resp["type"] == "pong"

def test_connection_manager_broadcast():
    import asyncio
    from src.api.websocket_manager import \
        ConnectionManager
    manager = ConnectionManager()
    # With no connections, broadcast should
    # not raise
    async def run():
        await manager.broadcast(
            {"type": "test"})
    asyncio.run(run())

def test_dashboard_has_websocket_script():
    """Verify dashboard HTML includes WebSocket client code."""
    token = "ws_dash_token"
    ACTIVE_SESSIONS[token] = "admin"
    response = client.get(
        "/dashboard",
        cookies={"session_token": token})
    assert response.status_code == 200
    assert "WebSocket" in response.text
    assert "ws-status" in response.text

def test_dashboard_has_connection_status():
    """Verify dashboard HTML includes connection status indicator."""
    token = "ws_conn_token"
    ACTIVE_SESSIONS[token] = "admin"
    response = client.get(
        "/dashboard",
        cookies={"session_token": token})
    assert response.status_code == 200
    assert "ws-status" in response.text

def test_jobs_table_has_tbody_id():
    """Verify jobs table has correct id for WebSocket updates."""
    token = "ws_table_token"
    ACTIVE_SESSIONS[token] = "admin"
    response = client.get(
        "/dashboard",
        cookies={"session_token": token})
    assert response.status_code == 200
    assert "jobs-tbody" in response.text
