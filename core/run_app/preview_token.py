"""Preview-origin tokens: how a browser gets into ONE run's generated app, and nothing else.

Generated apps are served from their own origin, a different one from the dashboard
AND from every other run: https://<run-id>.<AETHER_PREVIEW_ORIGIN host> (AETHER_PREVIEW_ORIGIN
is the base, e.g. https://preview.example.com; locally http://localhost:8100 gives
http://<run-id>.localhost:8100). One app's JavaScript therefore cannot read another run's
or org's session, cookies or storage, nor the dashboard's. Getting in is a two-step exchange:

  1. dashboard (signed in) → POST /factory/runs/{run_id}/preview-session
     → an ENTER token: run + org + user, audience = THAT RUN's origin,
       2 minutes, single use (it travels in a URL);
  2. browser → {run origin}/__preview/enter?t=<enter token>
     → the preview server spends it and sets a SESSION token as a host-only HttpOnly
       cookie on that run's origin (30 minutes).

Tokens are signed with AETHER_PREVIEW_SECRET (HS256), a key used for nothing
else: the preview server never holds the platform's JWT keys, and no preview
token can pass as a platform credential (different key, audience and purpose).
"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit

import jwt

ENTER, SESSION = "preview-enter", "preview-session"
ENTER_TTL_S, SESSION_TTL_S = 120, 30 * 60
SESSION_COOKIE = "aether_preview_session"
_ALG = "HS256"
_MIN_SECRET = 32

# The <iframe sandbox> the dashboard must use for previews (reported by the exchange endpoint).
# allow-same-origin keeps the PREVIEW origin (its cookie, its storage); it cannot reach the
# dashboard because the origins differ. No top navigation, no escaping the sandbox in popups.
IFRAME_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-modals"


def _origin(url: str) -> Optional[str]:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc.lower()}"


def preview_origin() -> Optional[str]:
    return _origin(os.environ.get("AETHER_PREVIEW_ORIGIN", ""))


_RUN_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}$")


def run_origin(run_id: str) -> str:
    """The origin that serves this run's app, and nothing else: <run-id>.<preview base host>."""
    base = preview_origin()
    if not base:
        raise RuntimeError("AETHER_PREVIEW_ORIGIN is not configured")
    if not _RUN_LABEL.match(run_id or ""):
        raise ValueError("run id cannot be used as a hostname label")
    scheme, _, netloc = base.partition("://")
    return f"{scheme}://{run_id}.{netloc}"


def origin_for_host(host: str) -> Optional[str]:
    """The run origin a request's Host header names, or None when it is not `<label>.<base host>`."""
    base = preview_origin()
    host = (host or "").strip().lower()
    if not base or not host:
        return None
    scheme, _, netloc = base.partition("://")
    label, sep, rest = host.partition(".")
    if not sep or rest != netloc or not _RUN_LABEL.match(label):
        return None
    return f"{scheme}://{host}"


def session_cookie_name() -> str:
    """__Host- on https: the browser then refuses any version set with a Domain attribute."""
    return ("__Host-" if (preview_origin() or "").startswith("https://") else "") + SESSION_COOKIE


def frame_src() -> Optional[str]:
    """CSP frame-src source for the dashboard: every run origin under the preview base."""
    base = preview_origin()
    if not base:
        return None
    scheme, _, netloc = base.partition("://")
    return f"{scheme}://*.{netloc}"


def dashboard_origin() -> Optional[str]:
    return _origin(os.environ.get("AETHER_DASHBOARD_ORIGIN") or os.environ.get("FRONTEND_URL", ""))


def config_problem(cors_origins: Iterable[str] = ()) -> Optional[str]:
    """Why previews must not be served right now, or None. Fail closed on any of these."""
    origin = preview_origin()
    if not origin:
        return "AETHER_PREVIEW_ORIGIN is not set to an http(s) origin"
    if len(os.environ.get("AETHER_PREVIEW_SECRET", "")) < _MIN_SECRET:
        return f"AETHER_PREVIEW_SECRET must be at least {_MIN_SECRET} characters"
    if origin == dashboard_origin():
        return "the preview origin must differ from the dashboard origin"
    if origin in {_origin(o) for o in cors_origins}:
        return "the dashboard's CORS_ORIGINS must not include the preview origin"
    return None


def _secret() -> str:
    secret = os.environ.get("AETHER_PREVIEW_SECRET", "")
    if len(secret) < _MIN_SECRET:
        raise RuntimeError("AETHER_PREVIEW_SECRET is not configured")
    return secret


def issue(run_id: str, org_id: str, user_id: str, purpose: str, ttl_s: int,
          now: Optional[float] = None) -> str:
    origin = run_origin(run_id)  # audience = this run's own origin
    now = time.time() if now is None else now
    claims = {"aud": origin, "purpose": purpose, "run_id": run_id, "org_id": org_id,
              "sub": str(user_id), "iat": int(now), "exp": int(now) + ttl_s,
              "jti": secrets.token_urlsafe(16)}
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def verify(token: str, purpose: str, origin: Optional[str],
           now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Claims of a valid token for this purpose and exactly this run origin, else None."""
    if not token or not origin:
        return None
    try:
        claims = jwt.decode(
            token, _secret(), algorithms=[_ALG], audience=origin,
            options={"require": ["exp", "iat", "aud", "jti", "run_id", "org_id", "sub", "purpose"],
                     "verify_exp": now is None},
        )
    except (jwt.PyJWTError, RuntimeError):
        return None
    if now is not None and claims["exp"] <= now:
        return None
    return claims if claims.get("purpose") == purpose else None


class ReplayGuard:
    """Remembers spent ENTER tokens until they expire.

    ponytail: in-process memory — correct while the preview server runs as one
    process (as configured). With several workers, move this set to Redis.
    """

    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def first_use(self, jti: str, exp: float, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
            if jti in self._seen:
                return False
            self._seen[jti] = exp
            return True
