"""KAN-99/KAN-109: generated service catalog verifies the JWT, has no default tenant, and reports DB errors."""
import importlib.util
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_api


def _load(tmp_path, with_auth):
    if with_auth:
        from jose import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        auth = types.ModuleType("src.auth")
        auth.ALGORITHM, auth._PUBLIC_KEY, auth.jwt = "RS256", pub, jwt
        sys.modules["src"] = types.ModuleType("src")
        sys.modules["src.auth"] = auth
    f = tmp_path / "catalog_api.py"
    f.write_text(generate_catalog_api([{"table": "vm"}], "demo", "python"))
    spec = importlib.util.spec_from_file_location("catalog_api", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, (priv if with_auth else None)


@pytest.fixture(autouse=True)
def _clean():
    yield
    for k in ("src", "src.auth", "catalog_api"):
        sys.modules.pop(k, None)


def _client(m, failing_db=False):
    app = FastAPI()
    app.include_router(m.catalog_router)

    class Sess:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")

        async def rollback(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    app.state.db_session = lambda: Sess()
    return TestClient(app)


def test_unsigned_token_and_no_token_are_rejected(tmp_path):
    m, priv = _load(tmp_path, True)
    c = _client(m)
    import base64, json
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    forged = f"{seg({'alg': 'none'})}.{seg({'sub': 'victim', 'type': 'access'})}.x"
    assert c.get("/api/platform/events", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert c.get("/api/platform/events").status_code == 401


def test_launch_db_failure_is_not_a_200(tmp_path):
    from jose import jwt
    m, priv = _load(tmp_path, True)
    tok = jwt.encode({"sub": "u1", "org_id": "o1", "type": "access"}, priv, algorithm="RS256")
    r = _client(m).post("/api/services/vm/launch", json={}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 503


def test_without_backend_auth_fails_closed(tmp_path):
    m, _ = _load(tmp_path, False)
    assert _client(m).get("/api/platform/events").status_code == 503
