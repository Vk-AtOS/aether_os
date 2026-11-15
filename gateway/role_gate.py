"""Default-deny role gate for every authenticated mutating request (D7).

Role checks used to be written by hand in each handler, so a handler that forgot one
was open to every signed-in user: a viewer could create webhooks, publish to the
marketplace, mint API keys. get_current_user now calls check_role() for every route,
so the floor is enforced centrally and a new router cannot opt out by omission.

  * viewer is read-only, except the self-service/read-like POSTs in VIEWER_MAY.
  * routes in ADMIN_ONLY change organisation-wide state: admin/owner only.
Handlers may still demand more (owner, superadmin, a policy action).
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import HTTPException, Request, status

from aether_os.core.policy.rules import ROLE_RANK

_SAFE = {"GET", "HEAD", "OPTIONS"}

# Route templates (or prefixes ending in "/") a viewer may still POST/PUT/PATCH/DELETE:
# their own session and preferences, read-like calls that happen to be POST, and the
# Velaris-backed surfaces (chat, mail, HR, control), where Velaris enforces its own roles.
VIEWER_MAY = (
    "/auth/logout", "/auth/change-password", "/auth/mfa/", "/account", "/account/preferences",
    "/settings/preferences", "/notifications/", "/memory/search", "/prime/", "/factory/estimate",
    "/factory/runs/{run_id}/sse-token", "/factory/runs/{run_id}/preview-session",
    "/chat/", "/mail/", "/hr/", "/velaris/", "/control/",
)

# Routes whose handler REALLY asks the policy engine (enforce / admit_run_start / the billing and plugin
# admin helpers): it decides by role, returns the structured denial the dashboard keys on and ledgers it,
# so the gate does not pre-empt it. EXACT templates only, never prefixes: a new route under the same
# prefix would silently lose the viewer floor. tests/test_role_gate.py verifies every entry by reading
# the handler, so an entry whose handler stops enforcing policy fails the build.
POLICY_GATED = (
    "/factory/start", "/mcp/start_pipeline", "/settings/test-provider", "/marketplace/install/{profile_id}",
    "/factory/runs/{run_id}/rerun", "/factory/runs/{run_id}/branch", "/factory/runs/{run_id}/restart",
    "/factory/runs/{run_id}/clarifying-answers", "/factory/runs/{run_id}/portal-tokens",
    "/factory/runs/{run_id}/portal-tokens/{token_id}",
    "/billing/create-order", "/billing/verify-payment", "/billing/cancel", "/billing/downgrade",
    "/billing/stripe/checkout",
    "/v2/plugins/install", "/v2/plugins/installed/{plugin_id}", "/v2/plugins/installed/{plugin_id}/config",
    "/v2/plugins/installed/{plugin_id}/test", "/v2/plugins/connectors/invoke",
    "/v2/plugins/connectors/ldap/authenticate", "/v2/plugins/connectors/ldap/users",
    "/v2/plugins/connectors/ldap/validate", "/v2/plugins/connectors/salesforce/query",
    "/v2/plugins/connectors/salesforce/validate",
    "/agents/{agent_name}/run",
)

# Organisation-wide state: outbound webhooks and publishing to the marketplace.
ADMIN_ONLY = ("/webhooks", "/marketplace/publish")


def _matches(template: str, rules: tuple) -> bool:
    return any(template == r or (r.endswith("/") and template.startswith(r)) or template.startswith(r + "/")
               for r in rules)


def _exact(template: str, rules: tuple) -> bool:
    return template in rules


def check_role(request: Request, user: Dict[str, Any]) -> None:
    """Raise 403 if `user`'s role may not make this (mutating) request."""
    if request.method in _SAFE:
        return
    route = request.scope.get("route")
    template = getattr(route, "path", None) or request.url.path
    role = user.get("role") or ""
    rank = ROLE_RANK.get(role)
    if rank is None:  # unknown role: deny by default
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown role")
    if _matches(template, ADMIN_ONLY) and rank < ROLE_RANK["admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    if role == "viewer" and not (_matches(template, VIEWER_MAY) or _exact(template, POLICY_GATED)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers have read-only access")


# An admin who must enrol in MFA may still do exactly this (enrol, sign out, read the policy).
MFA_ENROLMENT_OK = ("/auth/mfa/", "/auth/logout", "/auth/my-orgs", "/account/settings")


def check_admin_mfa(request: Request, user: Dict[str, Any], mfa_enabled: bool, org: Any, now: float = 0.0) -> None:
    """403 {"error": "mfa_required"} for an owner/admin without MFA once the org requires it and the
    grace period is over. Enforced here, on every authenticated request, because hiding admin UI
    is not security (D7) and an admin session is the most valuable thing to steal."""
    if mfa_enabled or not getattr(org, "require_admin_mfa", False):
        return
    if ROLE_RANK.get(user.get("role") or "", 0) < ROLE_RANK["admin"]:
        return
    if (getattr(org, "admin_mfa_grace_until", None) or 0) > (now or time.time()):
        return
    template = getattr(request.scope.get("route"), "path", None) or request.url.path
    if _matches(template, MFA_ENROLMENT_OK):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, {
        "error": "mfa_required", "message": "Your organisation requires administrators to enable MFA. "
                                            "Set it up at /auth/mfa/setup, then sign in again."})
