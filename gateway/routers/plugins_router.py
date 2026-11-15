"""
AetherOS — Plugins Router  (v2)

Catalog, installation, and generic connector invocation routes.
Skills, Salesforce, and LDAP connector routes live in plugins_connectors_router.py.
Mounted at /v2/plugins by the main API.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce

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


# ── Auth dependency ────────────────────────────────────────────────────────────

def _auth():
    return Depends(get_current_user)

async def _require_plugin_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Installing, configuring or invoking connectors uses org-wide credentials: admin only."""
    await enforce("plugin.manage", user)
    return user


def _admin():
    return Depends(_require_plugin_admin)


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
    user: Dict[str, Any] = _admin(),
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/installed/{plugin_id}")
async def uninstall_plugin(
    plugin_id: str,
    user: Dict[str, Any] = _admin(),
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
    user: Dict[str, Any] = _admin(),
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
    user: Dict[str, Any] = _admin(),
) -> Dict[str, Any]:
    """Test credentials for an installed plugin by making a real API call."""
    from aether_os.core.plugins.registry import get_plugin_registry
    from aether_os.core.plugins.connectors import get_connector, ConnectorError, assert_public_urls

    config = await get_plugin_registry().get_installed_config(plugin_id, user["org_id"])
    if config is None:
        raise HTTPException(status_code=404, detail="Plugin not installed")

    try:
        await assert_public_urls(config)
        connector = get_connector(plugin_id, config)
        result = await connector.test()
        return result
    except ConnectorError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        logger.warning("plugins_router: connector test failed for %s: %s", plugin_id, exc)
        return {"ok": False, "message": f"Unexpected error: {exc}"}


# ── Connector invocation ───────────────────────────────────────────────────────

@router.post("/connectors/invoke")
async def invoke_connector(
    req: ConnectorInvokeRequest,
    user: Dict[str, Any] = _admin(),
) -> Any:
    """
    Invoke a specific action on an installed connector.

    Example:
      POST /v2/plugins/connectors/invoke
      {"plugin_id": "github", "action": "create_pr", "params": {"repo": "org/repo", ...}}
    """
    from aether_os.core.plugins.registry import get_plugin_registry
    from aether_os.core.plugins.connectors import get_connector, ConnectorError, assert_public_urls

    config = await get_plugin_registry().get_installed_config(req.plugin_id, user["org_id"])
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plugin '{req.plugin_id}' is not installed for your org"
        )

    try:
        await assert_public_urls(config)
        connector = get_connector(req.plugin_id, config)
        result = await connector.invoke(req.action, req.params)
        return result
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Connector invoke failed [%s/%s]: %s", req.plugin_id, req.action, exc)
        raise HTTPException(status_code=500, detail=f"Connector error: {exc}") from exc

# Skills, Salesforce, and LDAP connector routes live in plugins_connectors_router.py —
# see gateway/routers/plugins_connectors_router.py
