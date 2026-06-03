"""
AetherOS — Connector Hub

Each connector wraps one external service with a clean async interface.
Connectors are called by pipeline phases and by the /connectors/invoke API.

All connectors:
  - Accept config dict (org-specific credentials from PluginRegistry)
  - Return structured dicts, not raw API responses
  - Raise ConnectorError on failure (never crash the pipeline)
  - Use httpx for HTTP calls (async, lightweight)
  - Have a test() method that validates credentials
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a connector call fails. Pipeline phases catch this."""
    pass


class BaseConnector:
    """Base class for all connectors."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    async def test(self) -> Dict[str, Any]:
        """Validate credentials. Subclasses must override this method.

        Returns {"ok": True, "latency_ms": float, "message": str} on success,
        or raises an exception on failure.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement test(). "
            "Return {'ok': True, 'latency_ms': float} on success or raise an exception."
        )

    async def invoke(self, action: str, params: Dict[str, Any]) -> Any:
        """Generic dispatch to action methods."""
        method = getattr(self, f"action_{action}", None)
        if not method:
            raise ConnectorError(f"Action '{action}' not supported by {self.__class__.__name__}")
        return await method(params)


# ── GitHub ────────────────────────────────────────────────────────────────────

class GitHubConnector(BaseConnector):
    """GitHub REST API v3 + GraphQL connector."""

    BASE = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        token = self.config.get("token", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.BASE}/user", headers=self._headers())
                if r.status_code == 200:
                    data = r.json()
                    return {"ok": True, "message": f"Connected as {data.get('login')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def action_list_repos(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        org = params.get("org") or self.config.get("default_org", "")
        url = f"{self.BASE}/orgs/{org}/repos" if org else f"{self.BASE}/user/repos"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers=self._headers(), params={"per_page": 50})
            r.raise_for_status()
            return [{"name": x["name"], "full_name": x["full_name"],
                     "default_branch": x["default_branch"], "url": x["html_url"]}
                    for x in r.json()]

    async def action_create_pr(self, params: Dict[str, Any]) -> Dict:
        import httpx
        repo = params["repo"]
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.BASE}/repos/{repo}/pulls",
                headers=self._headers(),
                json={
                    "title": params["title"],
                    "body": params.get("body", ""),
                    "head": params["head"],
                    "base": params.get("base", "main"),
                },
            )
            r.raise_for_status()
            data = r.json()
            return {"pr_number": data["number"], "url": data["html_url"], "state": data["state"]}

    async def action_create_issue(self, params: Dict[str, Any]) -> Dict:
        import httpx
        repo = params["repo"]
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.BASE}/repos/{repo}/issues",
                headers=self._headers(),
                json={
                    "title": params["title"],
                    "body": params.get("body", ""),
                    "labels": params.get("labels", []),
                },
            )
            r.raise_for_status()
            data = r.json()
            return {"issue_number": data["number"], "url": data["html_url"]}

    async def action_trigger_workflow(self, params: Dict[str, Any]) -> Dict:
        import httpx
        repo = params["repo"]
        workflow = params["workflow_id"]
        ref = params.get("ref", "main")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.BASE}/repos/{repo}/actions/workflows/{workflow}/dispatches",
                headers=self._headers(),
                json={"ref": ref, "inputs": params.get("inputs", {})},
            )
            r.raise_for_status()
            return {"triggered": True, "repo": repo, "workflow": workflow, "ref": ref}

    async def action_get_file_contents(self, params: Dict[str, Any]) -> Dict:
        import httpx, base64
        repo = params["repo"]
        path = params["path"]
        ref = params.get("ref", "main")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{self.BASE}/repos/{repo}/contents/{path}",
                headers=self._headers(),
                params={"ref": ref},
            )
            r.raise_for_status()
            data = r.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return {"path": path, "content": content, "sha": data.get("sha")}


# ── GitLab ────────────────────────────────────────────────────────────────────

class GitLabConnector(BaseConnector):
    def _base(self) -> str:
        return self.config.get("base_url", "https://gitlab.com").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.config.get("token", "")}

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self._base()}/api/v4/user", headers=self._headers())
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected as {r.json().get('username')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def action_list_projects(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{self._base()}/api/v4/projects",
                headers=self._headers(),
                params={"membership": True, "per_page": 50},
            )
            r.raise_for_status()
            return [{"id": x["id"], "name": x["name"], "url": x["web_url"]} for x in r.json()]

    async def action_create_mr(self, params: Dict[str, Any]) -> Dict:
        import httpx
        pid = params["project_id"]
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self._base()}/api/v4/projects/{pid}/merge_requests",
                headers=self._headers(),
                json={
                    "source_branch": params["source_branch"],
                    "target_branch": params.get("target_branch", "main"),
                    "title": params["title"],
                    "description": params.get("description", ""),
                },
            )
            r.raise_for_status()
            data = r.json()
            return {"iid": data["iid"], "url": data["web_url"], "state": data["state"]}


# ── Jira ──────────────────────────────────────────────────────────────────────

class JiraConnector(BaseConnector):
    def _auth(self):
        from httpx import BasicAuth
        return BasicAuth(self.config["email"], self.config["api_token"])

    def _base(self) -> str:
        return self.config["base_url"].rstrip("/")

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10, auth=self._auth()) as c:
                r = await c.get(f"{self._base()}/rest/api/3/myself",
                                headers={"Accept": "application/json"})
                if r.status_code == 200:
                    return {"ok": True, "message": f"Connected as {r.json().get('displayName')}"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def action_create_issue(self, params: Dict[str, Any]) -> Dict:
        import httpx
        async with httpx.AsyncClient(timeout=15, auth=self._auth()) as c:
            r = await c.post(
                f"{self._base()}/rest/api/3/issue",
                headers={"Content-Type": "application/json"},
                json={
                    "fields": {
                        "project": {"key": params["project_key"]},
                        "summary": params["summary"],
                        "description": {"type": "doc", "version": 1,
                                        "content": [{"type": "paragraph", "content":
                                                     [{"type": "text", "text": params.get("description", "")}]}]},
                        "issuetype": {"name": params.get("issue_type", "Task")},
                    }
                },
            )
            r.raise_for_status()
            data = r.json()
            return {"key": data["key"], "url": f"{self._base()}/browse/{data['key']}"}

    async def action_list_projects(self, params: Dict[str, Any]) -> List[Dict]:
        import httpx
        async with httpx.AsyncClient(timeout=15, auth=self._auth()) as c:
            r = await c.get(f"{self._base()}/rest/api/3/project",
                            headers={"Accept": "application/json"})
            r.raise_for_status()
            return [{"id": x["id"], "key": x["key"], "name": x["name"]} for x in r.json()]


# ── Linear ────────────────────────────────────────────────────────────────────

class LinearConnector(BaseConnector):
    API = "https://api.linear.app/graphql"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": self.config.get("api_key", ""),
                "Content-Type": "application/json"}

    async def _gql(self, query: str, variables: Dict = None) -> Dict:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(self.API, headers=self._headers(),
                             json={"query": query, "variables": variables or {}})
            r.raise_for_status()
            return r.json()

    async def test(self) -> Dict[str, Any]:
        try:
            data = await self._gql("{ viewer { name email } }")
            viewer = data.get("data", {}).get("viewer", {})
            if viewer:
                return {"ok": True, "message": f"Connected as {viewer.get('name')}"}
            return {"ok": False, "message": "Auth failed"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def action_create_issue(self, params: Dict[str, Any]) -> Dict:
        query = """
        mutation CreateIssue($title: String!, $teamId: String!, $description: String) {
          issueCreate(input: {title: $title, teamId: $teamId, description: $description}) {
            issue { id identifier url }
          }
        }"""
        data = await self._gql(query, {
            "title": params["title"],
            "teamId": params.get("team_id") or self.config.get("team_id", ""),
            "description": params.get("description", ""),
        })
        issue = data.get("data", {}).get("issueCreate", {}).get("issue", {})
        return {"id": issue.get("id"), "identifier": issue.get("identifier"),
                "url": issue.get("url")}


# ── Slack ─────────────────────────────────────────────────────────────────────

class SlackConnector(BaseConnector):
    API = "https://slack.com/api"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('bot_token', '')}",
                "Content-Type": "application/json"}

    async def test(self) -> Dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.API}/auth.test", headers=self._headers())
                data = r.json()
                if data.get("ok"):
                    return {"ok": True, "message": f"Connected as {data.get('user')} in {data.get('team')}"}
                return {"ok": False, "message": data.get("error", "Unknown error")}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def action_send_message(self, params: Dict[str, Any]) -> Dict:
        import httpx
        channel = params.get("channel") or self.config.get("channel", "#general")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.API}/chat.postMessage", headers=self._headers(),
                             json={"channel": channel, "text": params["text"],
                                   "blocks": params.get("blocks")})
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                raise ConnectorError(f"Slack error: {data.get('error')}")
            return {"ts": data.get("ts"), "channel": data.get("channel")}


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
