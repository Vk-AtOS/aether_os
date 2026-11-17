"""
AetherOS — SAML SSO Router (FastAPI)

Per-org IdP config is read from the SamlConfig DB table (populated via
PUT /settings/sso). Global env vars (SAML_*) are the fallback for orgs
that have not yet configured their own IdP.

Routes:
  GET  /auth/saml/metadata           — SP metadata XML (global / default SP config)
  GET  /auth/saml/login?org={slug}   — Redirect to org's IdP SSO URL
  POST /auth/saml/callback           — Process IdP response, issue JWT redirect

SP env vars (always required when SAML is used):
  SAML_SP_ENTITY_ID   — SP entity ID
  SAML_SP_ACS_URL     — Assertion Consumer Service callback URL
  FRONTEND_URL        — Where to redirect after successful auth
  OAUTH_REDIRECT_BASE — Fallback for FRONTEND_URL

Per-org IdP config stored in DB (takes precedence over env vars):
  SamlConfig.idp_entity_id, .idp_sso_url, .idp_cert
"""
from __future__ import annotations

import importlib.util

import logging
import os
import urllib.parse
import uuid
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation, User
from aether_os.gateway.auth import get_password_hash
from aether_os.gateway.auth_oauth import _signin_redirect
from aether_os.gateway.auth_refresh import _redis as token_store
from aether_os.gateway.policy_guard import enforce_seat

logger = logging.getLogger(__name__)
saml_router = APIRouter(prefix="/auth/saml", tags=["saml"])

# ── SP config (global — same for all orgs) ───────────────────────────────────

def _sp_entity_id() -> str:
    return os.environ.get("SAML_SP_ENTITY_ID", "")

def _sp_acs_url() -> str:
    return os.environ.get("SAML_SP_ACS_URL", "")

def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", os.environ.get("OAUTH_REDIRECT_BASE", "")).rstrip("/")

def _is_saml_usable() -> bool:
    return bool(_sp_entity_id() and _sp_acs_url())


# ── RelayState ────────────────────────────────────────────────────────────────

def _relay_state_for(org_slug: Optional[str]) -> str:
    """The RelayState this server issues at login: a relative path naming the org."""
    return "/login?" + urllib.parse.urlencode({"org": org_slug}) if org_slug else "/login"


def _org_from_relay_state(relay_state: Any) -> Optional[str]:
    """Org slug from a RelayState, or None.

    RelayState comes back in a browser POST, so anyone can set it. It is only
    honoured when it is a same-site relative path (what _relay_state_for issues);
    an absolute or scheme-relative URL, a backslash trick or control characters
    mean "no RelayState" and the callback falls back to its default. It is never
    used as a redirect target.
    """
    if not isinstance(relay_state, str) or not (0 < len(relay_state) <= 512):
        return None
    if not relay_state.startswith("/") or relay_state.startswith("//") or "\\" in relay_state:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in relay_state):
        return None
    try:
        parsed = urllib.parse.urlparse(relay_state)
        if parsed.scheme or parsed.netloc:
            return None
        return urllib.parse.parse_qs(parsed.query).get("org", [None])[0] or None
    except ValueError as exc:
        logger.warning("SAML: unparseable RelayState ignored: %s", exc)
        return None


# ── Per-org IdP config lookup ─────────────────────────────────────────────────

async def _get_idp_config_for_org(org_slug: Optional[str]) -> Optional[Dict[str, str]]:
    """Return {idp_entity_id, idp_sso_url, idp_cert, org_id} from DB for the given org slug.
    Falls back to env vars when org_slug is None or no DB record exists; org_id is
    None for that platform-operated fallback IdP."""
    if org_slug:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Organisation, SamlConfig
            from sqlalchemy import select
            sf = get_session_factory()
            async with sf() as session:
                org = (
                    await session.execute(select(Organisation).where(Organisation.slug == org_slug))
                ).scalar_one_or_none()
                if org:
                    cfg = (
                        await session.execute(
                            select(SamlConfig).where(SamlConfig.org_id == org.id)
                        )
                    ).scalar_one_or_none()
                    if cfg:
                        return {
                            "idp_entity_id": cfg.idp_entity_id,
                            "idp_sso_url": cfg.idp_sso_url,
                            "idp_cert": cfg.idp_cert,
                            "org_id": org.id,
                        }
        except Exception as exc:
            logger.debug("DB IdP lookup failed: %s", exc)

    # Env var fallback
    if (
        os.environ.get("SAML_IDP_ENTITY_ID")
        and os.environ.get("SAML_IDP_SSO_URL")
        and os.environ.get("SAML_IDP_CERT")
    ):
        return {
            "idp_entity_id": os.environ["SAML_IDP_ENTITY_ID"],
            "idp_sso_url": os.environ["SAML_IDP_SSO_URL"],
            "idp_cert": os.environ["SAML_IDP_CERT"],
            "org_id": None,
        }
    return None


async def _resolve_saml_user(email: str, idp_org_id: Optional[str]):
    """Map a validated SAML assertion to (user, org), or raise 403.

    A per-org IdP is configured by that org's own admins, so its assertions are
    only trusted for users of that org. Looking the email up globally let any
    tenant register an IdP, assert a victim's email and receive the victim's JWT.
    Only the platform env IdP (idp_org_id=None) may sign in or create any account.
    """
    sf = get_session_factory()
    async with sf() as session:
        row = (
            await session.execute(
                select(User, Organisation).join(Organisation).where(User.email == email)
            )
        ).fetchone()
        if row:
            user, org = row
            if idp_org_id and user.org_id != idp_org_id:
                logger.warning("SAML: IdP of org %s asserted a user of org %s — rejected", idp_org_id, user.org_id)
                raise HTTPException(status_code=403, detail="SAML identity does not belong to this organisation")
            if not user.is_active or user.deleted_at or org.is_deleted:
                raise HTTPException(status_code=403, detail="Account is deactivated")
            if not user.email_verified and not idp_org_id:
                # See auth_oauth._upsert_oauth_user: no auto-link of unverified accounts. A per-org IdP may
                # sign in its own org's members, which it provisioned unverified (below).
                raise HTTPException(status_code=403, detail="Verify your email address before signing in with SSO")
            return user, org
        if idp_org_id:
            # JIT-provision into the IdP's own org as a plain member — never a new owner.
            org = await session.get(Organisation, idp_org_id)
            if not org or org.is_deleted:
                raise HTTPException(status_code=403, detail="Organisation not found")
            await enforce_seat(org.id, "saml")  # JIT provisioning must not exceed the plan's seats
            role = "member"
            # The address is only asserted by that org's own IdP, which its admins control: it must not count
            # as verified, or a later Google/GitHub sign-in of the real owner of that address would be linked
            # into the attacker's org (KAN-69 F5).
            verified = False
        else:
            slug = email.split("@")[0].lower().replace(".", "-") + "-" + secrets.token_hex(3)
            org = Organisation(id=str(uuid.uuid4()), name=email, slug=slug, plan="trial")
            session.add(org)
            role = "owner"
            verified = True
        user = User(
            id=str(uuid.uuid4()), org_id=org.id, email=email,
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            role=role, email_verified=verified,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        await session.refresh(org)
        return user, org


def _build_saml_settings(idp: Dict[str, str]) -> Dict[str, Any]:
    return {
        "sp": {
            "entityId": _sp_entity_id(),
            "assertionConsumerService": {
                "url": _sp_acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {
            "entityId": idp["idp_entity_id"],
            "singleSignOnService": {
                "url": idp["idp_sso_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": idp["idp_cert"],
        },
        "strict": True,
        "debug": False,  # SEC-051: Never expose SAML XML debug errors
    }


def _build_request_dict(request: Request) -> Dict[str, Any]:
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", request.url.hostname),
        "script_name": request.url.path,
        "server_port": str(request.url.port or ("443" if request.url.scheme == "https" else "80")),
        "get_data": dict(request.query_params),
        "post_data": {},
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@saml_router.get("/available")
async def saml_available() -> dict:
    """Whether SSO sign-in can be offered. Public on purpose: the sign-in page
    asks before anyone is authenticated, and the answer reveals no tenant data."""
    return {"available": _is_saml_usable() and importlib.util.find_spec("onelogin") is not None}


@saml_router.get("/metadata")
async def saml_metadata() -> Response:
    """Return SP metadata XML using the global SP config."""
    if not _is_saml_usable():
        raise HTTPException(status_code=503, detail="SAML is not configured (set SAML_SP_ENTITY_ID and SAML_SP_ACS_URL)")
    # Use env var IdP or a dummy for metadata-only (SP metadata doesn't need IdP details)
    dummy_idp = {
        "idp_entity_id": os.environ.get("SAML_IDP_ENTITY_ID", "urn:dummy"),
        "idp_sso_url": os.environ.get("SAML_IDP_SSO_URL", "https://dummy"),
        "idp_cert": os.environ.get("SAML_IDP_CERT", "dummy"),
    }
    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings  # type: ignore
        settings = OneLogin_Saml2_Settings(_build_saml_settings(dummy_idp), sp_validation_only=True)
        metadata = settings.get_sp_metadata()
        return Response(content=metadata, media_type="application/xml")
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed") from None
    except Exception as exc:
        # SEC-051: Do not expose internal SAML error details in HTTP response
        logger.error("SAML metadata generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="SAML metadata generation failed") from exc


@saml_router.get("/login")
async def saml_login(
    request: Request,
    org: Optional[str] = Query(None, description="Org slug — resolves per-org IdP config"),
) -> RedirectResponse:
    """Redirect browser to the IdP SSO URL for the given org (or global fallback).
    Public on purpose: this is how an unauthenticated browser starts SSO."""
    if not _is_saml_usable():
        raise HTTPException(status_code=503, detail="SAML SP is not configured")
    idp = await _get_idp_config_for_org(org)
    if not idp:
        raise HTTPException(status_code=503, detail="No SAML IdP configured for this org")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
        req = _build_request_dict(request)
        auth = OneLogin_Saml2_Auth(req, _build_saml_settings(idp))
        # Without return_to the library sends its own URL (minus the query) as
        # RelayState, so the org never reached the callback.
        sso_url = auth.login(return_to=_relay_state_for(org))
        return RedirectResponse(url=sso_url)
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed") from None
    except Exception as exc:
        # SEC-051: Do not expose internal SAML error details in HTTP response
        logger.exception("SAML login initiation failed")
        raise HTTPException(status_code=500, detail="SAML login initiation failed") from exc


_ASSERTION_MIN_TTL_S, _ASSERTION_MAX_TTL_S = 300, 86400


async def _claim_assertion(auth: Any) -> bool:
    """Spend a SAML assertion id: True the first time, False on a replay (KAN-69 F16). A captured, still valid
    response could otherwise be posted again and again. SET NX in the shared token store, kept until the
    assertion itself expires; no id or an unreachable store is a denial, never "not used"."""
    assertion_id = auth.get_last_assertion_id()
    if not assertion_id:
        return False
    not_after = auth.get_last_assertion_not_on_or_after()
    ttl = int(not_after - time.time()) + 60 if not_after else _ASSERTION_MAX_TTL_S
    ttl = min(max(ttl, _ASSERTION_MIN_TTL_S), _ASSERTION_MAX_TTL_S)
    try:
        r = await token_store()
        return bool(await r.set(f"saml_used:{assertion_id}", "1", nx=True, ex=ttl))
    except Exception as exc:
        logger.warning("SAML replay check failed (Redis unavailable) - denying: %s", exc)
        return False


@saml_router.post("/callback")
async def saml_callback(request: Request) -> RedirectResponse:
    """Process IdP response, create/update user, redirect to frontend with JWT.
    Public on purpose: the signed SAML assertion in the body is the credential."""
    if not _is_saml_usable():
        raise HTTPException(status_code=503, detail="SAML SP is not configured")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed") from None

    form_data = await request.form()
    relay_state = form_data.get("RelayState", "")

    # Org slug from RelayState (issued by /login); anything but a relative path is ignored.
    org_slug = _org_from_relay_state(relay_state)

    idp = await _get_idp_config_for_org(org_slug)
    if not idp:
        # SEC-024: Do NOT silently pick an arbitrary org config — this is a security risk.
        # If RelayState didn't identify the org and no global fallback is configured, reject.
        logger.warning(
            "SAML callback: cannot determine organization from RelayState=%r (org_slug=%r)",
            str(relay_state)[:200],
            org_slug,
        )
        raise HTTPException(
            status_code=400,
            detail="Cannot determine organization from SAML response. "
                   "Ensure the RelayState includes the org parameter.",
        )

    req = _build_request_dict(request)
    req["post_data"] = dict(form_data)

    auth = OneLogin_Saml2_Auth(req, _build_saml_settings(idp))
    auth.process_response()

    if not auth.is_authenticated():
        errors = auth.get_errors()
        logger.warning("SAML authentication failed: %s", errors)
        frontend = _frontend_url()
        return RedirectResponse(
            url=f"{frontend}/login?error={urllib.parse.quote('SAML authentication failed')}",
            status_code=302,
        )

    if not await _claim_assertion(auth):
        logger.warning("SAML assertion replayed or not checkable: refused")
        return RedirectResponse(
            url=f"{_frontend_url()}/login?error={urllib.parse.quote('SAML authentication failed')}",
            status_code=302,
        )

    attrs = auth.get_attributes()
    name_id = auth.get_nameid()
    email = (
        (attrs.get("email") or
         attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or
         [name_id])[0]
    )

    try:
        user, org = await _resolve_saml_user(email, idp.get("org_id"))
    except HTTPException as exc:
        return RedirectResponse(
            url=f"{_frontend_url()}/login?error={urllib.parse.quote(str(exc.detail))}",
            status_code=302,
        )

    # a one-time code, never a token in the URL (logs, history, Referer); same exchange as OAuth (KAN-69 F8)
    return await _signin_redirect(user, org)
