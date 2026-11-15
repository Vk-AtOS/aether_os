"""
AetherOS — Plugins Connectors Router
=====================================
Skills, Salesforce connector, and LDAP/Active Directory connector endpoints.
Catalog, installation, and generic connector invocation live in plugins_router.py.

Routes
------
  POST /plugins/skills/generate
  GET  /plugins/skills
  POST /plugins/connectors/salesforce/validate
  POST /plugins/connectors/salesforce/objects
  POST /plugins/connectors/salesforce/objects/{object_name}/describe
  POST /plugins/connectors/salesforce/query
  POST /plugins/connectors/ldap/validate
  POST /plugins/connectors/ldap/users
  POST /plugins/connectors/ldap/authenticate
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aether_os.core.rate_limiter import get_rate_limiter
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plugins", tags=["plugins"])


# ── Request models ─────────────────────────────────────────────────────────────

class SkillGenerateRequest(BaseModel):
    skill_id: str
    params: Dict[str, Any] = {}


class SalesforceValidateRequest(BaseModel):
    instance_url: str
    access_token: str


class SalesforceDescribeRequest(BaseModel):
    instance_url: str
    access_token: str


class SalesforceQueryRequest(BaseModel):
    instance_url: str
    access_token: str
    soql: str


class LDAPValidateRequest(BaseModel):
    server: str
    bind_dn: str
    bind_password: str
    port: int = 389
    use_ssl: bool = False


class LDAPListUsersRequest(BaseModel):
    server: str
    bind_dn: str
    bind_password: str
    base_dn: str
    port: int = 389
    use_ssl: bool = False
    max_results: int = Field(default=500, ge=1, le=1000)


class LDAPAuthRequest(BaseModel):
    server: str
    bind_dn: str
    bind_password: str
    base_dn: str
    username: str
    password: str
    port: int = 389
    use_ssl: bool = False


# ── Auth dependency ────────────────────────────────────────────────────────────

def _auth():
    return Depends(get_current_user)

async def _require_plugin_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Installing, configuring or invoking connectors uses org-wide credentials: admin only."""
    await enforce("plugin.manage", user)
    return user


def _admin():
    return Depends(_require_plugin_admin)


# ── Skill generation ───────────────────────────────────────────────────────────

@router.post("/skills/generate")
async def generate_skill(
    req: SkillGenerateRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """
    Generate code using a skill.

    Example:
      POST /v2/plugins/skills/generate
      {"skill_id": "skill_auth", "params": {"framework": "fastapi", "auth_type": "jwt"}}
    """
    from aether_os.core.plugins.skills import get_skill

    try:
        skill = get_skill(req.skill_id)
        result = await skill.generate(req.params)
        return {
            "skill_id": req.skill_id,
            "files": result.get("files", {}),
            "dependencies": result.get("dependencies", []),
            "env_vars": result.get("env_vars", []),
            "file_count": len(result.get("files", {})),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Skill generate failed [%s]: %s", req.skill_id, exc)
        raise HTTPException(status_code=500, detail=f"Skill generation error: {exc}") from exc


@router.get("/skills")
async def list_available_skills(
    user: Dict[str, Any] = _auth(),
) -> List[Dict[str, Any]]:
    """List all available skills with their metadata."""
    from aether_os.core.plugins.registry import get_plugin_registry
    reg = get_plugin_registry()
    skills = reg.list_available(plugin_type="skill")
    return [p.to_dict() for p in skills]


async def _public_instance(instance_url: str) -> None:
    from aether_os.core.plugins.connectors import ConnectorError, assert_public_urls
    try:
        await assert_public_urls({"instance_url": instance_url})
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Salesforce connector endpoints ────────────────────────────────────────────

@router.post("/connectors/salesforce/validate")
async def validate_salesforce(
    req: SalesforceValidateRequest,
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Validate Salesforce credentials by calling the REST API root endpoint."""
    await _public_instance(req.instance_url)
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": req.instance_url, "access_token": req.access_token}
    )
    return await connector.validate(req.instance_url, req.access_token)


# POST, not GET: the access token must never be in a URL (access logs, proxies, history).
@router.post("/connectors/salesforce/objects")
async def list_salesforce_objects(
    req: SalesforceDescribeRequest,
    user: Dict[str, Any] = _admin(),
) -> List[str]:
    """List all available SObjects in the Salesforce org."""
    instance_url, access_token = req.instance_url, req.access_token
    await _public_instance(instance_url)
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": instance_url, "access_token": access_token}
    )
    try:
        return await connector.list_objects(instance_url, access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/salesforce/objects/{object_name}/describe")
async def describe_salesforce_object(
    object_name: str,
    req: SalesforceDescribeRequest,
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Describe a Salesforce SObject — returns fields and metadata."""
    instance_url, access_token = req.instance_url, req.access_token
    await _public_instance(instance_url)
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": instance_url, "access_token": access_token}
    )
    try:
        return await connector.describe_object(object_name, instance_url, access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/salesforce/query")
async def query_salesforce(
    req: SalesforceQueryRequest,
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Execute a SOQL query against Salesforce."""
    await _public_instance(req.instance_url)
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": req.instance_url, "access_token": req.access_token}
    )
    try:
        return await connector.query(req.soql, req.instance_url, req.access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── LDAP / Active Directory connector endpoints ───────────────────────────────

@router.post("/connectors/ldap/validate")
async def validate_ldap(
    req: LDAPValidateRequest,
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Test LDAP/Active Directory connectivity by performing a service account bind."""
    from aether_os.core.connectors.ldap_connector import LDAPConnector
    connector = LDAPConnector({
        "server": req.server,
        "bind_dn": req.bind_dn,
        "bind_password": req.bind_password,
        "port": req.port,
        "use_ssl": req.use_ssl,
    })
    return await connector.validate(req.server, req.bind_dn, req.bind_password)


@router.post("/connectors/ldap/users")
async def list_ldap_users(
    req: LDAPListUsersRequest,
    user: Dict[str, Any] = _admin(),
) -> List[Dict[str, Any]]:
    """Search for all user objects in the LDAP/AD directory."""
    from aether_os.core.connectors.ldap_connector import LDAPConnector
    connector = LDAPConnector({
        "server": req.server,
        "bind_dn": req.bind_dn,
        "bind_password": req.bind_password,
        "base_dn": req.base_dn,
        "port": req.port,
        "use_ssl": req.use_ssl,
    })
    try:
        return await connector.list_users(
            base_dn=req.base_dn,
            max_results=req.max_results,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/ldap/authenticate")
async def authenticate_ldap_user(
    req: LDAPAuthRequest,
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Authenticate a user against Active Directory / LDAP (a password oracle: 30 attempts per org per 10 minutes)."""
    if not await get_rate_limiter().allow(f"ldap_auth:{user['org_id']}", 30, 600):
        raise HTTPException(status_code=429, detail="Too many LDAP authentication attempts; try again later")
    from aether_os.core.connectors.ldap_connector import LDAPConnector
    connector = LDAPConnector({
        "server": req.server,
        "bind_dn": req.bind_dn,
        "bind_password": req.bind_password,
        "base_dn": req.base_dn,
        "port": req.port,
        "use_ssl": req.use_ssl,
    })
    try:
        ok = await connector.authenticate_user(
            username=req.username,
            password=req.password,
            base_dn=req.base_dn,
        )
        return {"authenticated": ok, "username": req.username}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
