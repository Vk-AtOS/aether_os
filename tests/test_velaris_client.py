"""Signing helper and role mapping, checked against Velaris's own verifier (skipped if the
Velaris repo is not next to this one)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aether_os.core.velaris import client as vc
from aether_os.core.velaris.client import Identity, VelarisUnavailable, sign_request
from aether_os.core.velaris.roles import MAY_ACT, VELARIS_ROLES, velaris_roles

VELARIS_REPO = Path(__file__).resolve().parents[2] / "Knackforge" / "velaris_knackforge"
SECRET = b"s" * 40
KEY = Ed25519PrivateKey.generate()
OWNER = Identity("u1", "org_a", "owner")


@pytest.fixture
def auth():
    if not (VELARIS_REPO / "velaris" / "api" / "auth.py").exists():
        pytest.skip("the Velaris repository is not available")
    sys.path.insert(0, str(VELARIS_REPO))
    try:
        from velaris.api import auth as velaris_auth
    except ImportError as e:
        pytest.skip(f"Velaris verifier not importable: {e}")
    finally:
        sys.path.remove(str(VELARIS_REPO))
    return velaris_auth


def verifier(auth, now=None):
    return auth.Verifier(SECRET, KEY.public_key(), clock=(lambda: now) if now else __import__("time").time)


def test_round_trip_is_accepted_by_velaris(auth):
    body = b'{"a":1}'
    headers = sign_request(SECRET, KEY, OWNER, "POST", "/agents/X/y?q=1", body)
    caller = verifier(auth).verify("POST", "/agents/X/y?q=1", {k.lower(): v for k, v in headers.items()}, body)
    assert (caller.id, caller.org, caller.employee_id) == ("u1", "org_a", None)
    assert caller.roles == VELARIS_ROLES["owner"]


def test_tampering_is_refused(auth):
    h = {k.lower(): v for k, v in sign_request(SECRET, KEY, OWNER, "GET", "/agents", b"").items()}
    for method, path, body in (("POST", "/agents", b""), ("GET", "/flows/pending", b""), ("GET", "/agents", b"x")):
        with pytest.raises(auth.AuthError) as e:
            verifier(auth).verify(method, path, h, body)
        assert e.value.code == "bad_signature"


def test_replay_and_stale_are_refused(auth):
    h = {k.lower(): v for k, v in sign_request(SECRET, KEY, OWNER, "GET", "/agents", b"").items()}
    v = verifier(auth)
    v.verify("GET", "/agents", h, b"")
    with pytest.raises(auth.AuthError) as e:
        v.verify("GET", "/agents", h, b"")
    assert e.value.code == "replay"
    old = {k.lower(): v_ for k, v_ in sign_request(SECRET, KEY, OWNER, "GET", "/agents", b"", now=1_000_000).items()}
    with pytest.raises(auth.AuthError) as e:
        verifier(auth).verify("GET", "/agents", old, b"")
    assert e.value.code == "stale"


def test_identity_cannot_be_swapped_or_signed_by_another_key(auth):
    a = {k.lower(): v for k, v in sign_request(SECRET, KEY, OWNER, "GET", "/agents", b"").items()}
    b = {k.lower(): v for k, v in sign_request(SECRET, KEY, Identity("u2", "org_a", "owner"), "GET", "/agents", b"").items()}
    with pytest.raises(auth.AuthError):      # a's MAC with b's identity
        verifier(auth).verify("GET", "/agents", {**a, "x-velaris-identity": b["x-velaris-identity"]}, b"")
    other = {k.lower(): v for k, v in sign_request(SECRET, Ed25519PrivateKey.generate(), OWNER, "GET", "/agents", b"").items()}
    with pytest.raises(auth.AuthError) as e:
        verifier(auth).verify("GET", "/agents", other, b"")
    assert e.value.code == "bad_identity"


def test_short_secret_is_refused():
    with pytest.raises(VelarisUnavailable):
        sign_request(b"short", KEY, OWNER, "GET", "/agents", b"")


def test_viewer_gets_no_roles_on_the_wire(auth):
    h = {k.lower(): v for k, v in sign_request(SECRET, KEY, Identity("u3", "org_a", "viewer"), "GET", "/agents", b"").items()}
    assert verifier(auth).verify("GET", "/agents", h, b"").roles == frozenset()


# ── role table ────────────────────────────────────────────────────────────────

def test_role_table_is_deny_by_default():
    assert velaris_roles("viewer") == velaris_roles("member") == frozenset()
    for unknown in (None, "", "api", "superuser", "OWNER"):
        assert velaris_roles(unknown) == frozenset()
    assert velaris_roles("admin") == {"hr_admin", "payroll_admin", "flow_approver", "model_admin", "mail_admin", "chat_admin"}
    assert {"governance_admin", "security_admin"} <= velaris_roles("owner")
    assert not {"governance_admin", "security_admin"} & velaris_roles("admin")
    assert MAY_ACT == {"owner", "admin", "member"}


def test_key_generation_is_owner_only_and_never_overwrites(tmp_path):
    p = str(tmp_path / "id.pem")
    vc.generate_identity_key(p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert isinstance(serialization.load_pem_private_key(Path(p).read_bytes(), None), Ed25519PrivateKey)
    with pytest.raises(FileExistsError):
        vc.generate_identity_key(p)


def test_from_env_fails_closed(monkeypatch, tmp_path):
    for k in ("VELARIS_API_URL", "VELARIS_API_SECRET", "VELARIS_IDENTITY_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(VelarisUnavailable):
        vc.VelarisClient.from_env()
    monkeypatch.setenv("VELARIS_API_URL", "http://v")
    monkeypatch.setenv("VELARIS_API_SECRET", "short")
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY", str(tmp_path / "missing.pem"))
    with pytest.raises(VelarisUnavailable):
        vc.VelarisClient.from_env()
