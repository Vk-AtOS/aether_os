"""
AetherOS — Plugins Router  (v2)

All plugin, connector, and skill management routes.
Mounted at /v2/plugins by the main API.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plugins", tags=["plugins"])


# ── Request models ─────────────────────────────────────────────────────────────

class InstallRequest(BaseModel):
    plugin_id: str
    config: Dict[str, Any] = {}


class UpdateConfigRequest(BaseModel):
    config: Dict[str, Any]


class ConnectorInvokeRequest(BaseModel):
    plugin_id: str
    action: str
    params: Dict[str, Any] = {}


class SkillGenerateRequest(BaseModel):
    skill_id: str
    params: Dict[str, Any] = {}


# ── Auth dependency ────────────────────────────────────────────────────────────

def _auth():
    return Depends(get_current_user)


# ── Catalog ────────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def list_catalog(
    type: Optional[str] = None,
    tag: Optional[str] = None,
    user: Dict[str, Any] = _auth(),
) -> List[Dict[str, Any]]:
    """Browse all available plugins in the built-in catalog."""
    from aether_os.core.plugins.registry import get_plugin_registry
    reg = get_plugin_registry()
    plugins = reg.list_available(plugin_type=type, tag=tag)
    return [p.to_dict() for p in plugins]


@router.get("/catalog/{plugin_id}")
async def get_plugin_manifest(
    plugin_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Get full manifest for a specific plugin."""
    from aether_os.core.plugins.registry import get_plugin_registry
    manifest = get_plugin_registry().get_manifest(plugin_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return manifest.to_dict()


# ── Installation ───────────────────────────────────────────────────────────────

@router.get("/installed")
async def list_installed(
    user: Dict[str, Any] = _auth(),
) -> List[Dict[str, Any]]:
    """List all plugins installed for this org."""
    from aether_os.core.plugins.registry import get_plugin_registry
    reg = get_plugin_registry()
    installed = await reg.get_installed(user["org_id"])
    result = []
    for plugin in installed:
        d = plugin.to_dict()
        # Enrich with manifest metadata
        manifest = reg.get_manifest(plugin.plugin_id)
        if manifest:
            d["name"] = manifest.name
            d["description"] = manifest.description
            d["icon"] = manifest.icon
            d["type"] = manifest.type
            d["capabilities"] = manifest.capabilities
        result.append(d)
    return result


@router.post("/install")
async def install_plugin(
    req: InstallRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Install a plugin for this org with the given config."""
    from aether_os.core.plugins.registry import get_plugin_registry
    reg = get_plugin_registry()
    plan = user.get("plan", "trial")
    try:
        installed = await reg.install(
            plugin_id=req.plugin_id,
            org_id=user["org_id"],
            config=req.config,
            plan=plan,
        )
        # Optionally test the connection immediately
        result = installed.to_dict()
        result["plugin_id"] = req.plugin_id
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.delete("/installed/{plugin_id}")
async def uninstall_plugin(
    plugin_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    """Uninstall a plugin for this org."""
    from aether_os.core.plugins.registry import get_plugin_registry
    ok = await get_plugin_registry().uninstall(plugin_id, user["org_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not installed")
    return {"status": "uninstalled", "plugin_id": plugin_id}


@router.put("/installed/{plugin_id}/config")
async def update_plugin_config(
    plugin_id: str,
    req: UpdateConfigRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    """Update the config (credentials) for an installed plugin."""
    from aether_os.core.plugins.registry import get_plugin_registry
    ok = await get_plugin_registry().update_config(plugin_id, user["org_id"], req.config)
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not installed or inactive")
    return {"status": "updated", "plugin_id": plugin_id}


@router.post("/installed/{plugin_id}/test")
async def test_plugin_connection(
    plugin_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Test credentials for an installed plugin by making a real API call."""
    from aether_os.core.plugins.registry import get_plugin_registry
    from aether_os.core.plugins.connectors import get_connector, ConnectorError

    config = await get_plugin_registry().get_installed_config(plugin_id, user["org_id"])
    if config is None:
        raise HTTPException(status_code=404, detail="Plugin not installed")

    try:
        connector = get_connector(plugin_id, config)
        result = await connector.test()
        return result
    except ConnectorError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": f"Unexpected error: {exc}"}


# ── Connector invocation ───────────────────────────────────────────────────────

@router.post("/connectors/invoke")
async def invoke_connector(
    req: ConnectorInvokeRequest,
    user: Dict[str, Any] = _auth(),
) -> Any:
    """
    Invoke a specific action on an installed connector.

    Example:
      POST /v2/plugins/connectors/invoke
      {"plugin_id": "github", "action": "create_pr", "params": {"repo": "org/repo", ...}}
    """
    from aether_os.core.plugins.registry import get_plugin_registry
    from aether_os.core.plugins.connectors import get_connector, ConnectorError

    config = await get_plugin_registry().get_installed_config(req.plugin_id, user["org_id"])
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plugin '{req.plugin_id}' is not installed for your org"
        )

    try:
        connector = get_connector(req.plugin_id, config)
        result = await connector.invoke(req.action, req.params)
        return result
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Connector invoke failed [%s/%s]: %s", req.plugin_id, req.action, exc)
        raise HTTPException(status_code=500, detail=f"Connector error: {exc}")


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
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Skill generate failed [%s]: %s", req.skill_id, exc)
        raise HTTPException(status_code=500, detail=f"Skill generation error: {exc}")


@router.get("/skills")
async def list_available_skills(
    user: Dict[str, Any] = _auth(),
) -> List[Dict[str, Any]]:
    """List all available skills with their metadata."""
    from aether_os.core.plugins.registry import get_plugin_registry
    reg = get_plugin_registry()
    skills = reg.list_available(plugin_type="skill")
    return [p.to_dict() for p in skills]


# ── Salesforce connector endpoints ────────────────────────────────────────────

class SalesforceValidateRequest(BaseModel):
    instance_url: str
    access_token: str


class SalesforceQueryRequest(BaseModel):
    instance_url: str
    access_token: str
    soql: str


@router.post("/connectors/salesforce/validate")
async def validate_salesforce(
    req: SalesforceValidateRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Validate Salesforce credentials by calling the REST API root endpoint."""
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": req.instance_url, "access_token": req.access_token}
    )
    return await connector.validate(req.instance_url, req.access_token)


@router.get("/connectors/salesforce/objects")
async def list_salesforce_objects(
    instance_url: str,
    access_token: str,
    user: Dict[str, Any] = _auth(),
) -> List[str]:
    """List all available SObjects in the Salesforce org."""
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector, ConnectorError as SF_ConnectorError
    connector = SalesforceConnector(
        {"instance_url": instance_url, "access_token": access_token}
    )
    try:
        return await connector.list_objects(instance_url, access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/connectors/salesforce/objects/{object_name}/describe")
async def describe_salesforce_object(
    object_name: str,
    instance_url: str,
    access_token: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Describe a Salesforce SObject — returns fields and metadata."""
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": instance_url, "access_token": access_token}
    )
    try:
        return await connector.describe_object(object_name, instance_url, access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/connectors/salesforce/query")
async def query_salesforce(
    req: SalesforceQueryRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Execute a SOQL query against Salesforce."""
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    connector = SalesforceConnector(
        {"instance_url": req.instance_url, "access_token": req.access_token}
    )
    try:
        return await connector.query(req.soql, req.instance_url, req.access_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── LDAP / Active Directory connector endpoints ───────────────────────────────

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
    max_results: int = 500


class LDAPAuthRequest(BaseModel):
    server: str
    bind_dn: str
    bind_password: str
    base_dn: str
    username: str
    password: str
    port: int = 389
    use_ssl: bool = False


@router.post("/connectors/ldap/validate")
async def validate_ldap(
    req: LDAPValidateRequest,
    user: Dict[str, Any] = _auth(),
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
    user: Dict[str, Any] = _auth(),
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
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/connectors/ldap/authenticate")
async def authenticate_ldap_user(
    req: LDAPAuthRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Authenticate a user against Active Directory / LDAP."""
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
        raise HTTPException(status_code=400, detail=str(exc))
