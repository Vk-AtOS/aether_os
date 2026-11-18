"""AetherOS organisation role -> Velaris roles. The one table; deny by default.

Velaris roles are organisation-wide (velaris/core/access.py): hr_admin reads every
employee's records, payroll_admin pay and bank data, governance_admin changes Prime-style
grants and policies, security_admin zero-trust settings, flow_approver decides runs
(local mode only; with Prime, approvals are decided in AetherOS Prime).

A role not in the table (viewer, api, anything unknown, None) gets no Velaris role.
The mapping is intentionally narrow: only owner and admin hold admin roles, and the two
most sensitive ones (governance_admin, security_admin) are the owner's alone. mail_admin and chat_admin (mailbox provisioning, retention, DKIM; chat compliance export and erasure: without them
Velaris refused every one of those routes for everybody) are held by owner and admin. model_admin (model providers and their
keys, velaris/api/providers_api.py) is held by owner and admin, like the organisation's own API-key settings.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, FrozenSet, Optional

logger = logging.getLogger(__name__)

VELARIS_ROLES: Dict[str, FrozenSet[str]] = {
    "owner": frozenset({"hr_admin", "payroll_admin", "flow_approver", "model_admin", "mail_admin", "chat_admin",
                        "governance_admin", "security_admin"}),
    "admin": frozenset({"hr_admin", "payroll_admin", "flow_approver", "model_admin", "mail_admin", "chat_admin"}),
    "member": frozenset(),
    "viewer": frozenset(),
}
# Roles that may start work in Velaris at all (call agent methods, start flows).
# A viewer may look at the catalogue and nothing else.
MAY_ACT: FrozenSet[str] = frozenset({"owner", "admin", "member"})
# Roles that may do organisation-wide or personal-data-wide things (exports, erasure, payroll runs, mailbox
# provisioning). Checked in the gateway on every such row; Velaris applies its own roles on top.
ADMIN_ROLES: FrozenSet[str] = frozenset({"owner", "admin"})


# Velaris roles that exist (recruiter, hiring_manager, interviewer, atlassian_reader) but that no
# AetherOS org role holds by default, so the screens behind them refuse everybody (KAN-104).
# An operator grants them by configuration, never in code:
#   AETHER_VELARIS_ROLE_GRANTS='{"member": ["recruiter", "interviewer"], "admin": ["hiring_manager"]}'
# Default: no grant. Only these roles can be granted this way; the admin roles above cannot, an
# unknown role name is ignored with a warning, and malformed JSON grants nothing (fails closed).
CONFIGURABLE_ROLES: FrozenSet[str] = frozenset(
    {"recruiter", "hiring_manager", "interviewer", "atlassian_reader"})


def _configured_grants() -> Dict[str, FrozenSet[str]]:
    raw = os.environ.get("AETHER_VELARIS_ROLE_GRANTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("must be a JSON object of org role -> list of Velaris roles")
        out: Dict[str, FrozenSet[str]] = {}
        for org_role, names in data.items():
            if not isinstance(names, list):
                raise ValueError(f"{org_role!r}: expected a list")
            ok = frozenset(n for n in names if n in CONFIGURABLE_ROLES)
            for n in set(names) - ok:
                logger.warning("AETHER_VELARIS_ROLE_GRANTS: %r is not a configurable Velaris role: ignored", n)
            out[str(org_role)] = ok
        return out
    except (ValueError, TypeError) as exc:
        logger.warning("AETHER_VELARIS_ROLE_GRANTS is not usable, granting nothing extra: %s", exc)
        return {}


def velaris_roles(org_role: Optional[str]) -> FrozenSet[str]:
    base = VELARIS_ROLES.get(org_role or "", frozenset())
    extra = _configured_grants().get(org_role or "", frozenset())
    return base | extra


# Which Velaris roles may read OTHER people's records of a sensitive category. Mirrors
# velaris.core.access.READ_OTHERS; a category not listed here is refused (deny by default).
READ_OTHERS: Dict[str, FrozenSet[str]] = {
    "pay": frozenset({"payroll_admin", "hr_admin"}),
    "bank": frozenset({"payroll_admin"}),
    "identity": frozenset({"hr_admin"}),
    "health": frozenset({"hr_admin"}),
}
