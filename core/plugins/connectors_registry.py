"""
AetherOS — Connector Registry & Extended Connector Implementations

Contains Figma, Vercel, Sentry, Supabase, AWS, GCP, Stripe, PlanetScale connectors
plus the connector factory function.  Core base classes and GitHub/GitLab/Jira/
Linear/Slack connectors live in connectors.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from aether_os.core.plugins.connectors import (
    BaseConnector,
    ConnectorError,
    GitHubConnector,
    GitLabConnector,
    JiraConnector,
    LinearConnector,
    SlackConnector,
)

logger = logging.getLogger(__name__)


# ── Figma ─────────────────────────────────────────────────────────────────────

class FigmaConnector(BaseConnector):
    API = "https://api.figma.com/v1"

    def _headers(self) -> Dict[str, str]:
        return {"X-Figma-Token": self.config.get("access_token", "")}

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.API}/me", headers=self._headers())
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected as {r.json().get('email')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("FigmaConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def action_get_file(self, params: Dict[str, Any]) -> Dict:
        import httpx
        file_key = params["file_key"]
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.API}/files/{file_key}", headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return {"name": data.get("name"), "last_modified": data.get("lastModified"),
                    "pages": [p["name"] for p in data.get("document", {}).get("children", [])]}

    async def action_export_component(self, params: Dict[str, Any]) -> Dict:
        import httpx
        file_key = params["file_key"]
        node_ids = params["node_ids"]  # comma-separated
        fmt = params.get("format", "SVG")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.API}/images/{file_key}",
                headers=self._headers(),
                params={"ids": node_ids, "format": fmt},
            )
            r.raise_for_status()
            return r.json().get("images", {})


# ── Vercel ────────────────────────────────────────────────────────────────────

class VercelConnector(BaseConnector):
    API = "https://api.vercel.com"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('token', '')}"}

    def _team_param(self) -> Dict[str, str]:
        tid = self.config.get("team_id", "")
        return {"teamId": tid} if tid else {}

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.API}/v2/user", headers=self._headers())
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected as {r.json().get('user', {}).get('email')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("VercelConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def action_list_projects(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.API}/v9/projects", headers=self._headers(),
                            params=self._team_param())
            r.raise_for_status()
            return [{"id": x["id"], "name": x["name"], "framework": x.get("framework")}
                    for x in r.json().get("projects", [])]

    async def action_get_env(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        project_id = params["project_id"]
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.API}/v9/projects/{project_id}/env",
                            headers=self._headers(), params=self._team_param())
            r.raise_for_status()
            envs = r.json().get("envs", [])
            return [{"key": e["key"], "target": e.get("target"), "type": e.get("type")} for e in envs]


# ── Sentry ────────────────────────────────────────────────────────────────────

class SentryConnector(BaseConnector):
    API = "https://sentry.io/api/0"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('auth_token', '')}"}

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.API}/", headers=self._headers())
                if r.status_code == 200:
                    return {"ok": True, "message": "Sentry connected"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("SentryConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def action_list_projects(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        org = self.config.get("org_slug", "")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.API}/organizations/{org}/projects/",
                            headers=self._headers())
            r.raise_for_status()
            return [{"id": x["id"], "slug": x["slug"], "name": x["name"]} for x in r.json()]

    def generate_sdk_config(self, platform: str = "python") -> str:
        dsn = self.config.get("dsn", "YOUR_DSN")
        configs = {
            "python": f'import sentry_sdk\nsentry_sdk.init(dsn="{dsn}", traces_sample_rate=1.0)',
            "javascript": f'import * as Sentry from "@sentry/browser";\nSentry.init({{ dsn: "{dsn}" }});',
            "react": f'import * as Sentry from "@sentry/react";\nSentry.init({{ dsn: "{dsn}", tracesSampleRate: 1.0 }});',
            "nextjs": f'// sentry.client.config.js\nimport * as Sentry from "@sentry/nextjs";\nSentry.init({{ dsn: "{dsn}" }});',
        }
        return configs.get(platform, configs["python"])


# ── Supabase ──────────────────────────────────────────────────────────────────

class SupabaseConnector(BaseConnector):
    def _base(self) -> str:
        return self.config.get("url", "").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.config.get("anon_key", ""),
            "Authorization": f"Bearer {self.config.get('service_key') or self.config.get('anon_key', '')}",
        }

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self._base()}/rest/v1/", headers=self._headers())
                if r.status_code in (200, 400):  # 400 means connected but no table specified
                    return {"ok": True, "message": "Supabase connected"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("SupabaseConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    def generate_client_code(self, framework: str = "javascript") -> str:
        url = self._base()
        key = self.config.get("anon_key", "YOUR_ANON_KEY")
        if framework == "javascript":
            return (f"import {{ createClient }} from '@supabase/supabase-js';\n"
                    f"export const supabase = createClient('{url}', '{key}');")
        if framework == "python":
            return (f"from supabase import create_client\n"
                    f"supabase = create_client('{url}', '{key}')")
        return ""


# ── Stub connectors (AWS, GCP, Stripe, PlanetScale) ───────────────────────────
# These provide credential validation + code generation helpers.
# Full SDK calls are added incrementally without breaking the pipeline.

class AWSConnector(BaseConnector):
    async def test(self) -> Dict[str, Any]:
        try:
            import boto3  # type: ignore
            session = boto3.Session(
                aws_access_key_id=self.config.get("access_key_id"),
                aws_secret_access_key=self.config.get("secret_access_key"),
                region_name=self.config.get("region", "us-east-1"),
            )
            sts = session.client("sts")
            identity = sts.get_caller_identity()
            return {"ok": True, "message": f"Connected as {identity.get('Arn')}"}
        except ImportError:
            return {"ok": False, "message": "boto3 not installed"}
        except Exception as exc:
            logger.warning("AWSConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}


class GCPConnector(BaseConnector):
    async def test(self) -> Dict[str, Any]:
        return {"ok": True, "message": "GCP connector configured (credentials not validated at install time)"}


class StripeConnector(BaseConnector):
    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    "https://api.stripe.com/v1/account",
                    auth=(self.config.get("secret_key", ""), ""),
                )
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected to {r.json().get('display_name', 'Stripe')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("StripeConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}


class PlanetScaleConnector(BaseConnector):
    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            org = self.config.get("org", "")
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"https://api.planetscale.com/v1/organizations/{org}",
                    headers={"Authorization": f"{self.config.get('service_token_id')}:{self.config.get('service_token')}"},
                )
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected to org {org}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("PlanetScaleConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}


# ── Connector factory ─────────────────────────────────────────────────────────

def _lazy_salesforce():
    from aether_os.core.connectors.salesforce_connector import SalesforceConnector
    return SalesforceConnector


def _lazy_ldap():
    from aether_os.core.connectors.ldap_connector import LDAPConnector
    return LDAPConnector


_CONNECTOR_MAP: Dict[str, type] = {
    "github": GitHubConnector,
    "gitlab": GitLabConnector,
    "jira": JiraConnector,
    "linear": LinearConnector,
    "slack": SlackConnector,
    "figma": FigmaConnector,
    "vercel": VercelConnector,
    "aws": AWSConnector,
    "gcp": GCPConnector,
    "stripe": StripeConnector,
    "supabase": SupabaseConnector,
    "planetscale": PlanetScaleConnector,
    "sentry": SentryConnector,
}

# Enterprise connectors — loaded lazily to avoid hard import of optional deps
_ENTERPRISE_CONNECTOR_FACTORIES: Dict[str, Any] = {
    "salesforce": _lazy_salesforce,
    "ldap":       _lazy_ldap,
    "activedirectory": _lazy_ldap,  # alias
}


def get_connector(plugin_id: str, config: Dict[str, Any]) -> BaseConnector:
    """Instantiate the connector for the given plugin_id."""
    cls = _CONNECTOR_MAP.get(plugin_id)
    if cls:
        return cls(config)
    # Enterprise connectors loaded lazily
    factory = _ENTERPRISE_CONNECTOR_FACTORIES.get(plugin_id)
    if factory:
        return factory()(config)
    raise ConnectorError(f"No connector implemented for plugin '{plugin_id}'")
