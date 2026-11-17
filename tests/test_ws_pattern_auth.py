"""KAN-69 G4: the generated websocket pattern verified /broadcast tokens with an empty HS256 secret (a forged token
passed, real RS256 tokens never validated) and anyone could join any room. Runs the real generated auth.py with the
pattern in a subprocess (the generated app has top-level modules named auth, ws)."""
import json
import subprocess
import sys

from aether_os.phases.p04a_backend_codegen.templates_auth import _AUTH_PY
from aether_os.phases.patterns.websocket import WEBSOCKET_CODE

_RUN = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
os.environ["RSA_PRIVATE_KEY_PATH"] = os.path.join(os.getcwd(), "k.pem")
import jwt, auth, ws
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI(); app.include_router(ws.router)
out = {}
with TestClient(app) as c:
    forged = jwt.encode({"sub": "1"}, "", algorithm="HS256")
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
