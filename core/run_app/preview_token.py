"""Preview-origin tokens: how a browser gets into ONE run's generated app, and nothing else.

Generated apps are served from AETHER_PREVIEW_ORIGIN, a different origin from
the dashboard, so their JavaScript cannot read the dashboard's storage or call
the platform API as the signed-in user. Getting in is a two-step exchange:

  1. dashboard (signed in) → POST /factory/runs/{run_id}/preview-session
     → an ENTER token: run + org + user, audience = the preview origin,
       2 minutes, single use (it travels in a URL);
  2. browser → {preview origin}/__preview/enter?t=<enter token>
     → the preview server spends it and sets a SESSION token as an HttpOnly
       cookie on the preview origin only (30 minutes).

Tokens are signed with AETHER_PREVIEW_SECRET (HS256), a key used for nothing
else: the preview server never holds the platform's JWT keys, and no preview
token can pass as a platform credential (different key, audience and purpose).
"""
from __future__ import annotations

import os
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
    origin = preview_origin()
    if not origin:
        raise RuntimeError("AETHER_PREVIEW_ORIGIN is not configured")
    now = time.time() if now is None else now
    claims = {"aud": origin, "purpose": purpose, "run_id": run_id, "org_id": org_id,
              "sub": str(user_id), "iat": int(now), "exp": int(now) + ttl_s,
              "jti": secrets.token_urlsafe(16)}
    return jwt.encode(claims, _secret(), algorithm=_ALG)


def verify(token: str, purpose: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Claims of a valid token for this purpose and THIS preview origin, else None."""
    origin = preview_origin()
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
