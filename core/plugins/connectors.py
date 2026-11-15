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

import asyncio
import logging
from typing import Any, Dict, List, Optional

from aether_os.core.security.safe_http import UnsafeURL, resolve_public, safe_request

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a connector call fails. Pipeline phases catch this."""
    pass


# Config keys that hold an address the ORG typed in (everything else points at a fixed vendor API).
_ORG_URL_KEYS = ("base_url", "url", "instance_url")


async def assert_public_urls(config: Dict[str, Any]) -> None:
    """Refuse connector configs that point at the platform's own network (SSRF).

    Every address the host resolves to must be public (core.security.safe_http).
    Raises ConnectorError.
    """
    for key in _ORG_URL_KEYS:
        value = config.get(key)
        if value:
            try:
                await asyncio.to_thread(resolve_public, str(value))
            except UnsafeURL as exc:
                raise ConnectorError(f"{key} rejected: {exc}") from exc


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
            logger.warning("GitHubConnector.test failed: %s", exc)
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
            r = await safe_request("GET", f"{self._base()}/api/v4/user", timeout=10, headers=self._headers())
            if r.status_code == 200:
                return {"ok": True, "message": f"Connected as {r.json().get('username')}"}
            return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("GitLabConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def action_list_projects(self, params: Dict[str, Any]) -> List[Dict]:
        r = await safe_request(
            "GET", f"{self._base()}/api/v4/projects", timeout=15,
            headers=self._headers(), params={"membership": True, "per_page": 50},
        )
        r.raise_for_status()
        return [{"id": x["id"], "name": x["name"], "url": x["web_url"]} for x in r.json()]

    async def action_create_mr(self, params: Dict[str, Any]) -> Dict:
        pid = params["project_id"]
        r = await safe_request(
            "POST", f"{self._base()}/api/v4/projects/{pid}/merge_requests", timeout=15,
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
            r = await safe_request("GET", f"{self._base()}/rest/api/3/myself", timeout=10,
                                   auth=self._auth(), headers={"Accept": "application/json"})
            if r.status_code == 200:
                return {"ok": True, "message": f"Connected as {r.json().get('displayName')}"}
            return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as exc:
            logger.warning("JiraConnector.test failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    async def action_create_issue(self, params: Dict[str, Any]) -> Dict:
        r = await safe_request(
            "POST", f"{self._base()}/rest/api/3/issue", timeout=15, auth=self._auth(),
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
        r = await safe_request("GET", f"{self._base()}/rest/api/3/project", timeout=15,
                               auth=self._auth(), headers={"Accept": "application/json"})
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
            logger.warning("LinearConnector.test failed: %s", exc)
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
            logger.warning("SlackConnector.test failed: %s", exc)
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


# ── Re-exports from connectors_registry ──────────────────────────────────────
# Extended connectors (Figma, Vercel, Sentry, Supabase, AWS, GCP, Stripe,
# PlanetScale) and the factory function live in connectors_registry.py.
# They are re-exported here so all existing callers continue to work.
from aether_os.core.plugins.connectors_registry import (  # noqa: F401
    FigmaConnector,
    VercelConnector,
    SentryConnector,
    SupabaseConnector,
    AWSConnector,
    GCPConnector,
    StripeConnector,
    PlanetScaleConnector,
    get_connector,
    _CONNECTOR_MAP,
    _ENTERPRISE_CONNECTOR_FACTORIES,
)
