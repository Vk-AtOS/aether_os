"""Signed calls to the Velaris HTTP API (the proofs velaris/api/auth.py verifies).

Every request carries
  1. a service credential: HMAC-SHA256 (VELARIS_API_SECRET, >= 32 bytes) over
     METHOD \\n PATH?QUERY \\n TIMESTAMP \\n NONCE \\n sha256(body) \\n sha256(identity header);
  2. an identity assertion: base64url(claims) "." base64url(Ed25519 signature), signed with
     VELARIS_IDENTITY_PRIVATE_KEY (PEM path). Claims: iss aetheros, aud velaris, sub, org,
     roles, employee_id, iat, exp (ttl <= 300 s) and nonce (= the request's nonce).

Environment: VELARIS_API_URL, VELARIS_API_SECRET, VELARIS_IDENTITY_PRIVATE_KEY.
Velaris holds only the public key and VELARIS_ORG must equal the AetherOS org id.

Owner setup (once, on the AetherOS side; never created automatically):
    umask 077 && openssl genpkey -algorithm ED25519 -out velaris_identity.pem
    openssl pkey -in velaris_identity.pem -pubout -out velaris_identity.pub.pem
The .pub.pem goes to Velaris (VELARIS_IDENTITY_PUBLIC_KEY); the private one stays here.

The identity comes only from the caller's verified sign-in row, never from request input.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aether_os.core.resilience import BulkheadFull, CircuitOpen, get_breaker, get_bulkhead
from aether_os.core.velaris.roles import velaris_roles

logger = logging.getLogger(__name__)

MIN_SECRET_BYTES = 32
ASSERTION_TTL_S = 60            # Velaris accepts at most 300
DEFAULT_TIMEOUT_S = 30.0        # a Velaris call may itself take up to 60 s; callers may pass less


class VelarisUnavailable(Exception):
    """Velaris is not configured, not reachable, or answered garbage. Maps to HTTP 503."""


async def _guarded(call):
    """Run one upstream call behind the 'velaris' breaker and bulkhead (KAN-49).

    Only VelarisUnavailable (transport failure, 502/503/504, non-JSON) counts as a failure, so Velaris's own 4xx answers
    never open the breaker. After 5 failures calls fail at once for 30 s instead of each holding a connection for the
    full timeout; at most VELARIS_MAX_INFLIGHT calls wait on Velaris at once, so a stuck Velaris cannot absorb every
    request handler of this worker.
    """
    try:
        async with get_bulkhead("velaris", limit=int(os.environ.get("VELARIS_MAX_INFLIGHT", "32"))):
            return await get_breaker("velaris", failure_threshold=5, reset_after_s=30.0).call(
                call, is_failure=lambda e: isinstance(e, VelarisUnavailable))
    except CircuitOpen:
        raise VelarisUnavailable("Velaris is unavailable (circuit open)") from None
    except BulkheadFull:
        raise VelarisUnavailable("Velaris is busy") from None


@dataclass(frozen=True)
class Identity:
    """Who the call is for. Built from the user's DB row (org role), never from a request."""
    user_id: str
    org_id: str
    org_role: Optional[str]
    employee_id: Optional[str] = None   # ponytail: AetherOS users have no linked employee record yet


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def canonical(method: str, path: str, ts: str, nonce: str, body: bytes, identity: str) -> bytes:
    return "\n".join([method.upper(), path, ts, nonce, hashlib.sha256(body).hexdigest(),
                      hashlib.sha256(identity.encode()).hexdigest()]).encode()


def make_assertion(key: Ed25519PrivateKey, who: Identity, nonce: str, *, ttl: int = ASSERTION_TTL_S,
                   now: Optional[float] = None) -> str:
    iat = int(time.time() if now is None else now)
    claims = {"iss": "aetheros", "aud": "velaris", "sub": who.user_id, "org": who.org_id,
              "roles": sorted(velaris_roles(who.org_role)), "employee_id": who.employee_id,
              "iat": iat, "exp": iat + min(ttl, 300), "nonce": nonce}
    payload = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    return f"{payload}.{_b64(key.sign(payload.encode()))}"


def sign_request(secret: bytes, key: Ed25519PrivateKey, who: Identity, method: str, path: str,
                 body: bytes, *, now: Optional[float] = None, nonce: Optional[str] = None) -> Dict[str, str]:
    """The four X-Velaris-* headers for one request. `path` includes the query string."""
    if len(secret) < MIN_SECRET_BYTES:
        raise VelarisUnavailable("VELARIS_API_SECRET is shorter than 32 bytes")
    nonce = nonce or secrets.token_urlsafe(24)
    ts = str(int(time.time() if now is None else now))
    identity = make_assertion(key, who, nonce, now=now)
    mac = hmac.new(secret, canonical(method, path, ts, nonce, body, identity), hashlib.sha256).hexdigest()
    return {"X-Velaris-Timestamp": ts, "X-Velaris-Nonce": nonce, "X-Velaris-Signature": mac,
            "X-Velaris-Identity": identity}


def generate_identity_key(path: str) -> None:
    """Explicit, owner-run only: write a new Ed25519 private key (mode 0600). Refuses to overwrite."""
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)


def _load_key(path: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as e:
        logger.warning("velaris identity key unreadable: %s", type(e).__name__)
        raise VelarisUnavailable("the Velaris identity key could not be read") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise VelarisUnavailable("the Velaris identity key is not an Ed25519 key")
    return key


class VelarisClient:
    def __init__(self, base_url: str, secret: bytes, key: Ed25519PrivateKey, *, timeout: float = DEFAULT_TIMEOUT_S,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._secret, self._key, self._timeout, self._transport = secret, key, timeout, transport
        self._base = base_url.rstrip("/")

    @classmethod
    def from_env(cls, *, timeout: float = DEFAULT_TIMEOUT_S,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> "VelarisClient":
        url = os.environ.get("VELARIS_API_URL", "").strip()
        secret = os.environ.get("VELARIS_API_SECRET", "").encode()
        key_path = os.environ.get("VELARIS_IDENTITY_PRIVATE_KEY", "").strip()
        if not (url and secret and key_path):
            raise VelarisUnavailable("Velaris is not connected")
        if len(secret) < MIN_SECRET_BYTES:
            raise VelarisUnavailable("VELARIS_API_SECRET is shorter than 32 bytes")
        return cls(url, secret, _load_key(key_path), timeout=timeout, transport=transport)

    def _signed(self, who: Identity, method: str, path: str, query: str, body: bytes,
                content_type: Optional[str]) -> Tuple[str, Dict[str, str]]:
        target = path + (f"?{query}" if query else "")
        headers = sign_request(self._secret, self._key, who, method, target, body)
        if body:
            headers["Content-Type"] = content_type or "application/json"
        return target, headers

    async def request_raw(self, who: Identity, method: str, path: str, *, body: bytes = b"", query: str = "",
                          content_type: Optional[str] = None, timeout: Optional[float] = None) -> httpx.Response:
        """The Velaris response as it is (bytes, any content type): for raw uploads/downloads and
        pre-serialised JSON. Raises VelarisUnavailable when Velaris cannot be reached or answers 502/503/504."""
        target, headers = self._signed(who, method, path, query, body, content_type)

        async def call() -> httpx.Response:
            try:
                async with httpx.AsyncClient(base_url=self._base, timeout=timeout or self._timeout,
                                             transport=self._transport, follow_redirects=False) as http:
                    resp = await http.request(method, target, content=body or None, headers=headers)
            except httpx.HTTPError as e:
                logger.warning("velaris unreachable: %s", type(e).__name__)
                raise VelarisUnavailable("Velaris could not be reached") from None
            if resp.status_code in (502, 503, 504):
                raise VelarisUnavailable("Velaris is not available")
            return resp
        return await _guarded(call)

    async def open_stream(self, who: Identity, path: str, *, query: str = "",
                          read_timeout: float = 60.0) -> Tuple[httpx.AsyncClient, httpx.Response]:
        """GET that is read as it arrives (Server-Sent Events). The caller must `await resp.aclose()` and
        `await http.aclose()`; cancelling the reader and closing drops the upstream connection."""
        target, headers = self._signed(who, "GET", path, query, b"", None)

        async def call() -> Tuple[httpx.AsyncClient, httpx.Response]:
            http = httpx.AsyncClient(base_url=self._base, transport=self._transport, follow_redirects=False,
                                     timeout=httpx.Timeout(10.0, read=read_timeout))
            try:
                resp = await http.send(http.build_request("GET", target, headers=headers), stream=True)
            except httpx.HTTPError as e:
                await http.aclose()
                logger.warning("velaris unreachable: %s", type(e).__name__)
                raise VelarisUnavailable("Velaris could not be reached") from None
            if resp.status_code in (502, 503, 504):
                await resp.aclose()
                await http.aclose()
                raise VelarisUnavailable("Velaris is not available")
            return http, resp
        return await _guarded(call)

    async def request(self, who: Identity, method: str, path: str, *, json_body: Any = None,
                      query: str = "") -> Tuple[int, Any]:
        """(HTTP status, parsed JSON) from Velaris. Raises VelarisUnavailable when it cannot be reached
        or does not answer with JSON. Velaris's own errors (4xx/5xx with a body) are returned, not raised."""
        body = b"" if json_body is None else json.dumps(json_body, separators=(",", ":")).encode()
        target = path + (f"?{query}" if query else "")
        headers = sign_request(self._secret, self._key, who, method, target, body)
        if body:
            headers["Content-Type"] = "application/json"

        async def call() -> Tuple[int, Any]:
            try:
                async with httpx.AsyncClient(base_url=self._base, timeout=self._timeout, transport=self._transport,
                                             follow_redirects=False) as http:
                    resp = await http.request(method, target, content=body or None, headers=headers)
            except httpx.HTTPError as e:
                logger.warning("velaris unreachable: %s", type(e).__name__)
                raise VelarisUnavailable("Velaris could not be reached") from None
            try:
                data = resp.json()
            except ValueError:
                logger.warning("velaris answered HTTP %s without JSON", resp.status_code)
                raise VelarisUnavailable("Velaris answered with something that is not JSON") from None
            if resp.status_code in (502, 503, 504):
                raise VelarisUnavailable("Velaris is not available")
            return resp.status_code, data
        return await _guarded(call)
