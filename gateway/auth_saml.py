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

import logging
import os
import urllib.parse
import uuid
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

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


# ── Per-org IdP config lookup ─────────────────────────────────────────────────

async def _get_idp_config_for_org(org_slug: Optional[str]) -> Optional[Dict[str, str]]:
    """Return {idp_entity_id, idp_sso_url, idp_cert} from DB for the given org slug.
    Falls back to env vars when org_slug is None or no DB record exists."""
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
        }
    return None


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
        raise HTTPException(status_code=503, detail="python3-saml not installed")
    except Exception as exc:
        # SEC-051: Do not expose internal SAML error details in HTTP response
        logger.error("SAML metadata generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="SAML metadata generation failed")


@saml_router.get("/login")
async def saml_login(
    request: Request,
    org: Optional[str] = Query(None, description="Org slug — resolves per-org IdP config"),
) -> RedirectResponse:
    """Redirect browser to the IdP SSO URL for the given org (or global fallback)."""
    if not _is_saml_usable():
        raise HTTPException(status_code=503, detail="SAML SP is not configured")
    idp = await _get_idp_config_for_org(org)
    if not idp:
        raise HTTPException(status_code=503, detail="No SAML IdP configured for this org")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
        req = _build_request_dict(request)
        auth = OneLogin_Saml2_Auth(req, _build_saml_settings(idp))
        sso_url = auth.login()
        return RedirectResponse(url=sso_url)
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed")
    except Exception as exc:
        # SEC-051: Do not expose internal SAML error details in HTTP response
        logger.exception("SAML login initiation failed")
        raise HTTPException(status_code=500, detail="SAML login initiation failed")


@saml_router.post("/callback")
async def saml_callback(request: Request) -> RedirectResponse:
    """Process IdP response, create/update user, redirect to frontend with JWT."""
    if not _is_saml_usable():
        raise HTTPException(status_code=503, detail="SAML SP is not configured")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed")

    form_data = await request.form()
    relay_state = form_data.get("RelayState", "")

    # Try to extract org slug from RelayState (passed through from login initiation)
    org_slug: Optional[str] = None
    if relay_state:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(relay_state).query)
            org_slug = parsed.get("org", [None])[0]
        except Exception:
            pass

    idp = await _get_idp_config_for_org(org_slug)
    if not idp:
        # SEC-024: Do NOT silently pick an arbitrary org config — this is a security risk.
        # If RelayState didn't identify the org and no global fallback is configured, reject.
        logger.warning(
            "SAML callback: cannot determine organization from RelayState=%r (org_slug=%r)",
            relay_state,
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

    attrs = auth.get_attributes()
    name_id = auth.get_nameid()
    email = (
        (attrs.get("email") or
         attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or
         [name_id])[0]
    )

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import create_access_token, get_password_hash
    from sqlalchemy import select

    sf = get_session_factory()
    async with sf() as session:
        row = (
            await session.execute(
                select(User, Organisation).join(Organisation).where(User.email == email)
            )
        ).fetchone()
        if row:
            user, org = row
        else:
            slug = email.split("@")[0].lower().replace(".", "-") + "-" + secrets.token_hex(3)
            org = Organisation(id=str(uuid.uuid4()), name=email, slug=slug, plan="trial")
            session.add(org)
            user = User(
                id=str(uuid.uuid4()), org_id=org.id, email=email,
                password_hash=get_password_hash(secrets.token_urlsafe(32)),
                role="owner",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            await session.refresh(org)

    from aether_os.gateway.auth import create_refresh_token as _crt_saml
    _saml_claims = {
        "sub": user.email, "user_id": user.id,
        "org_id": org.id, "org_slug": org.slug,
        "role": user.role, "plan": org.plan,
    }
    token = create_access_token(_saml_claims)
    refresh = _crt_saml(_saml_claims)
    frontend = _frontend_url()
    return RedirectResponse(
        url=(
            f"{frontend}/auth/callback"
            f"?token={urllib.parse.quote(token)}"
            f"&refresh_token={urllib.parse.quote(refresh)}"
        ),
        status_code=302,
    )
