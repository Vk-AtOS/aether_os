"""KAN-69 G4: the generated websocket pattern verified /broadcast tokens with an empty HS256 secret (a forged token
passed, real RS256 tokens never validated) and anyone could join any room. Runs the real generated auth.py with the
pattern in a subprocess (the generated app has top-level modules named auth, ws)."""
import json
import subprocess
import sys

from aether_os.phases.p04a_backend_codegen.templates_auth import _AUTH_PY
from aether_os.phases.patterns.websocket import WEBSOCKET_CODE

_RUN = r'''
import base64, hashlib, hmac, json, os, sys
sys.path.insert(0, os.getcwd())
os.environ["RSA_PRIVATE_KEY_PATH"] = os.path.join(os.getcwd(), "k.pem")
import auth, ws
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI(); app.include_router(ws.router)
out = {}
with TestClient(app) as c:
    # HS256 signed with the EMPTY key, built by hand: PyJWT >= 2.13 refuses to sign with an empty key.
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    body = b64(b'{"alg":"HS256","typ":"JWT"}') + "." + b64(b'{"sub":"1"}')
    forged = body + "." + b64(hmac.new(b"", body.encode(), hashlib.sha256).digest())
    out["no_token"] = c.post("/ws/r/broadcast", json={}).status_code
    out["forged"] = c.post("/ws/r/broadcast", json={}, headers={"Authorization": "Bearer " + forged}).status_code
    ta = auth.create_access_token(1, "a@x.io", "user", org_id="A")
    tb = auth.create_access_token(2, "b@x.io", "user", org_id="B")
    out["valid"] = c.post("/ws/r/broadcast", json={"x": 1}, headers={"Authorization": "Bearer " + ta}).status_code
    try:
        with c.websocket_connect("/ws/r"):
            out["anon_ws"] = "accepted"
    except Exception as e:
        out["anon_ws"] = type(e).__name__
    with c.websocket_connect("/ws/r?token=" + ta) as a, c.websocket_connect("/ws/r?token=" + tb) as b:
        a.receive_json(); b.receive_json()
        c.post("/ws/r/broadcast", json={"x": 2}, headers={"Authorization": "Bearer " + ta})
        out["a_got"] = a.receive_json()["data"]
        out["b_members"] = ws.manager.room_count("B:r"), ws.manager.room_count("A:r")
print("RESULT" + json.dumps(out))
'''


def test_broadcast_and_join_need_the_apps_own_token_and_rooms_are_per_tenant(tmp_path):
    (tmp_path / "auth.py").write_text(_AUTH_PY)
    (tmp_path / "ws.py").write_text(WEBSOCKET_CODE)
    (tmp_path / "run.py").write_text(_RUN)
    p = subprocess.run([sys.executable, str(tmp_path / "run.py")], cwd=tmp_path, capture_output=True, text=True, timeout=25)
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")]
    assert line, p.stdout + p.stderr[-2000:]
    out = json.loads(line[0][6:])
    assert out["no_token"] == 401 and out["forged"] == 401 and out["valid"] == 200, out
    assert out["anon_ws"] != "accepted", out
    assert out["a_got"] == {"x": 2} and out["b_members"] == [1, 1], out


_HB = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
os.environ["RSA_PRIVATE_KEY_PATH"] = os.path.join(os.getcwd(), "k.pem")
os.environ["WS_HEARTBEAT_SECONDS"] = "0.2"
os.environ["WS_MAX_MESSAGE_BYTES"] = "50"
import auth, ws
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI(); app.include_router(ws.router)
out = {}
with TestClient(app) as c:
    t = auth.create_access_token(1, "a@x.io", "user", org_id="A")
    with c.websocket_connect("/ws/r?token=" + t) as a:
        out["hello"] = a.receive_json()["type"]
        out["ping"] = a.receive_json()["type"]                       # silent for one interval -> ping
        a.send_text(json.dumps({"type": "pong"}))                     # answered: stays open, not broadcast
        a.send_text(json.dumps({"x": 1}))
        out["echo"] = a.receive_json()
        out["members"] = ws.manager.room_count("A:r")
        a.send_text("x" * 200)                                        # too big -> closed
        try:
            while True:
                a.receive_json()
        except Exception as e:
            out["closed_big"] = type(e).__name__
    # a peer that never answers is dropped after two intervals
    with c.websocket_connect("/ws/r?token=" + t) as b:
        b.receive_json(); b.receive_json()                            # connected, ping 1
        try:
            while True:
                b.receive_json()
        except Exception as e:
            out["closed_silent"] = type(e).__name__
    out["left_in_room"] = ws.manager.room_count("A:r")
print("RESULT" + json.dumps(out))
'''


def test_generated_websocket_pings_drops_dead_peers_and_bounds_messages(tmp_path):
    """KAN-187: auth existed, there was no heartbeat (a dead peer held its slot forever) and no size bound."""
    (tmp_path / "auth.py").write_text(_AUTH_PY)
    (tmp_path / "ws.py").write_text(WEBSOCKET_CODE)
    (tmp_path / "run.py").write_text(_HB)
    p = subprocess.run([sys.executable, str(tmp_path / "run.py")], cwd=tmp_path, capture_output=True, text=True, timeout=40)
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")]
    assert line, p.stdout + p.stderr[-2000:]
    out = json.loads(line[0][6:])
    assert out["hello"] == "connected" and out["ping"] == "ping", out
    assert out["echo"] == {"type": "message", "room": "r", "data": {"x": 1}}, out
    assert out["closed_big"] == "WebSocketDisconnect" and out["closed_silent"] == "WebSocketDisconnect", out
    assert out["left_in_room"] == 0, out
