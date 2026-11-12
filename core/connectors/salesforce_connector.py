"""
Salesforce CRM connector — OAuth2 connected app authentication.

Authentication flow:
  1. Create a Salesforce Connected App with OAuth2 enabled.
  2. Obtain an access_token via the OAuth2 flow (or use a long-lived session token
     from the Salesforce CLI: `sf org display --json`).
  3. Pass instance_url and access_token to any method below.

All methods are async and use httpx.  They raise ConnectorError on failure.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from aether_os.core.plugins.connectors import BaseConnector, ConnectorError
from aether_os.core.security.safe_http import safe_request

logger = logging.getLogger(__name__)

_API_VERSION = "v58.0"


class SalesforceConnector(BaseConnector):
    """
    Salesforce REST API connector.

    Expected config keys:
      instance_url  — e.g. https://yourorg.my.salesforce.com
      access_token  — OAuth2 bearer token (or session ID from SOAP login)
    """

    def _instance_url(self) -> str:
        url = self.config.get("instance_url", "").rstrip("/")
        if not url:
            raise ConnectorError("Salesforce connector requires 'instance_url' in config")
        return url

    def _headers(self) -> Dict[str, str]:
        token = self.config.get("access_token", "")
        if not token:
            raise ConnectorError("Salesforce connector requires 'access_token' in config")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _api_base(self) -> str:
        return f"{self._instance_url()}/services/data/{_API_VERSION}"

    # ── Core methods ──────────────────────────────────────────────────────────

    async def validate(
        self,
        instance_url: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Verify credentials by calling the Salesforce REST API root endpoint.

        Returns {"ok": True, "instance_url": ..., "api_version": ...} on success.
        """
        try:
            url = (instance_url or self._instance_url()).rstrip("/")
            token = access_token or self.config.get("access_token", "")
            if not token:
                return {"ok": False, "message": "access_token is required"}
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            r = await safe_request(
                "GET", f"{url}/services/data/{_API_VERSION}/", timeout=10,
                headers=headers,
            )
            if r.status_code == 200:
                return {
                    "ok": True,
                    "instance_url": url,
                    "api_version": _API_VERSION,
                    "message": "Salesforce connection verified",
                }
            return {
                "ok": False,
                "message": f"HTTP {r.status_code}: {r.text[:200]}",
            }
        except Exception as exc:
            logger.warning("salesforce_connector validate failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def test(self) -> Dict[str, Any]:
        """BaseConnector compatibility — delegates to validate()."""
        return await self.validate()

    async def list_objects(
        self,
        instance_url: str | None = None,
        access_token: str | None = None,
    ) -> List[str]:
        """
        List available SObjects (standard and custom) in the org.

        Returns a sorted list of API names, e.g. ["Account", "Contact", "Lead", ...].
        """
        try:
            url = (instance_url or self._instance_url()).rstrip("/")
            token = access_token or self.config.get("access_token", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            r = await safe_request(
                "GET", f"{url}/services/data/{_API_VERSION}/sobjects/", timeout=20,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            sobjects = data.get("sobjects", [])
            return sorted(obj["name"] for obj in sobjects if obj.get("name"))
        except Exception as exc:
            raise ConnectorError(f"Salesforce list_objects failed: {exc}") from exc

    async def describe_object(
        self,
        object_name: str,
        instance_url: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Describe a Salesforce SObject — returns field list, relationships, and metadata.

        Args:
            object_name: API name of the SObject, e.g. "Account", "Lead", "CustomObj__c"

        Returns a dict with keys: name, label, fields (list of field dicts), createable,
        updateable, queryable, searchable.
        """
        try:
            url = (instance_url or self._instance_url()).rstrip("/")
            token = access_token or self.config.get("access_token", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            r = await safe_request(
                "GET", f"{url}/services/data/{_API_VERSION}/sobjects/{object_name}/describe/", timeout=20,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            # Return a curated subset — full response can be 500KB+
            return {
                "name": data.get("name"),
                "label": data.get("label"),
                "createable": data.get("createable", False),
                "updateable": data.get("updateable", False),
                "queryable": data.get("queryable", False),
                "searchable": data.get("searchable", False),
                "fields": [
                    {
                        "name": f["name"],
                        "label": f["label"],
                        "type": f["type"],
                        "nillable": f.get("nillable", True),
                        "length": f.get("length"),
                    }
                    for f in data.get("fields", [])
                ],
            }
        except Exception as exc:
            raise ConnectorError(
                f"Salesforce describe_object({object_name}) failed: {exc}"
            ) from exc

    async def query(
        self,
        soql: str,
        instance_url: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Execute a SOQL query and return the results.

        Args:
            soql: Valid SOQL string, e.g. "SELECT Id, Name FROM Account LIMIT 10"

        Returns {"totalSize": int, "done": bool, "records": [...]}.
        """
        try:
            url = (instance_url or self._instance_url()).rstrip("/")
            token = access_token or self.config.get("access_token", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            r = await safe_request(
                "GET", f"{url}/services/data/{_API_VERSION}/query/", timeout=30,
                headers=headers,
                params={"q": soql},
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise ConnectorError(f"Salesforce query failed: {exc}") from exc

    # ── BaseConnector action dispatch ─────────────────────────────────────────

    async def action_list_objects(self, params: Dict[str, Any]) -> List[str]:
        return await self.list_objects()

    async def action_describe_object(self, params: Dict[str, Any]) -> Dict[str, Any]:
        object_name = params.get("object_name") or params.get("name", "")
        if not object_name:
            raise ConnectorError("action_describe_object requires 'object_name' param")
        return await self.describe_object(object_name)

    async def action_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        soql = params.get("soql", "")
        if not soql:
            raise ConnectorError("action_query requires 'soql' param")
        return await self.query(soql)
