"""
AetherOS — SAML SSO Router (FastAPI)

Mounts at /auth/saml via api.py:
    app.include_router(saml_router)

Requires env vars:
    SAML_SP_ENTITY_ID   — SP entity ID (usually your ACS URL base)
    SAML_SP_ACS_URL     — ACS callback URL (https://yourdomain/auth/saml/callback)
    SAML_IDP_ENTITY_ID  — IdP entity ID
    SAML_IDP_SSO_URL    — IdP SSO URL
    SAML_IDP_CERT       — IdP X.509 certificate (PEM, no headers)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

logger = logging.getLogger(__name__)
saml_router = APIRouter(prefix="/auth/saml", tags=["saml"])


def _saml_settings() -> Dict[str, Any]:
    return {
        "sp": {
            "entityId": os.environ.get("SAML_SP_ENTITY_ID", ""),
            "assertionConsumerService": {
                "url": os.environ.get("SAML_SP_ACS_URL", ""),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {
            "entityId": os.environ.get("SAML_IDP_ENTITY_ID", ""),
            "singleSignOnService": {
                "url": os.environ.get("SAML_IDP_SSO_URL", ""),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": os.environ.get("SAML_IDP_CERT", ""),
        },
        "strict": True,
        "debug": os.environ.get("ENVIRONMENT") != "production",
    }


def _is_saml_configured() -> bool:
    return bool(
        os.environ.get("SAML_SP_ENTITY_ID")
        and os.environ.get("SAML_IDP_ENTITY_ID")
        and os.environ.get("SAML_IDP_SSO_URL")
        and os.environ.get("SAML_IDP_CERT")
    )


def _build_saml_request(request: Request) -> Dict[str, Any]:
    """Convert a FastAPI Request into the dict python3-saml expects."""
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", request.url.hostname),
        "script_name": request.url.path,
        "server_port": str(request.url.port or ("443" if request.url.scheme == "https" else "80")),
        "get_data": dict(request.query_params),
        "post_data": {},  # populated in the callback after body is read
    }


@saml_router.get("/metadata")
async def saml_metadata() -> Response:
    """Return SP metadata XML for IdP configuration."""
    if not _is_saml_configured():
        raise HTTPException(status_code=503, detail="SAML is not configured")
    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings  # type: ignore
        settings = OneLogin_Saml2_Settings(_saml_settings(), sp_validation_only=True)
        metadata, errors = settings.get_sp_metadata(), []
        if errors:
            raise HTTPException(status_code=500, detail=f"SAML metadata error: {errors}")
        return Response(content=metadata, media_type="application/xml")
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed")


@saml_router.get("/login")
async def saml_login(request: Request) -> RedirectResponse:
    """Redirect browser to IdP SSO URL."""
    if not _is_saml_configured():
        raise HTTPException(status_code=503, detail="SAML is not configured")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
        req = _build_saml_request(request)
        auth = OneLogin_Saml2_Auth(req, _saml_settings())
        sso_url = auth.login()
        return RedirectResponse(url=sso_url)
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed")
    except Exception as exc:
        logger.exception("SAML login initiation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@saml_router.post("/callback")
async def saml_callback(request: Request) -> Dict[str, str]:
    """Process IdP response, create/update user, return JWT."""
    if not _is_saml_configured():
        raise HTTPException(status_code=503, detail="SAML is not configured")
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="python3-saml not installed")

    form_data = await request.form()
    req = _build_saml_request(request)
    req["post_data"] = dict(form_data)

    auth = OneLogin_Saml2_Auth(req, _saml_settings())
    auth.process_response()

    if not auth.is_authenticated():
        errors = auth.get_errors()
        logger.warning("SAML authentication failed: %s", errors)
        raise HTTPException(status_code=401, detail=f"SAML authentication failed: {errors}")

    attrs = auth.get_attributes()
    name_id = auth.get_nameid()
    email = (
        (attrs.get("email") or attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or [name_id])[0]
    )

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import create_access_token, get_password_hash
    from sqlalchemy import select
    import uuid, secrets

    sf = get_session_factory()
    async with sf() as session:
        row = (await session.execute(select(User, Organisation).join(Organisation).where(User.email == email))).fetchone()
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

    token = create_access_token({
        "sub": user.email, "user_id": user.id,
        "org_id": org.id, "org_slug": org.slug,
        "role": user.role, "plan": org.plan,
    })
    return {"access_token": token, "token_type": "bearer"}
