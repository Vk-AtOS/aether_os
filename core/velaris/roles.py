"""AetherOS organisation role -> Velaris roles. The one table; deny by default.

Velaris roles are organisation-wide (velaris/core/access.py): hr_admin reads every
employee's records, payroll_admin pay and bank data, governance_admin changes Prime-style
grants and policies, security_admin zero-trust settings, flow_approver decides runs
(local mode only; with Prime, approvals are decided in AetherOS Prime).

A role not in the table (viewer, api, anything unknown, None) gets no Velaris role.
The mapping is intentionally narrow: only owner and admin hold admin roles, and the two
most sensitive ones (governance_admin, security_admin) are the owner's alone. model_admin (model providers and their
keys, velaris/api/providers_api.py) is held by owner and admin, like the organisation's own API-key settings.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional

VELARIS_ROLES: Dict[str, FrozenSet[str]] = {
    "owner": frozenset({"hr_admin", "payroll_admin", "flow_approver", "model_admin",
                        "governance_admin", "security_admin"}),
    "admin": frozenset({"hr_admin", "payroll_admin", "flow_approver", "model_admin"}),
    "member": frozenset(),
    "viewer": frozenset(),
}
# Roles that may start work in Velaris at all (call agent methods, start flows).
# A viewer may look at the catalogue and nothing else.
MAY_ACT: FrozenSet[str] = frozenset({"owner", "admin", "member"})


def velaris_roles(org_role: Optional[str]) -> FrozenSet[str]:
    return VELARIS_ROLES.get(org_role or "", frozenset())


# Which Velaris roles may read OTHER people's records of a sensitive category. Mirrors
# velaris.core.access.READ_OTHERS; a category not listed here is refused (deny by default).
READ_OTHERS: Dict[str, FrozenSet[str]] = {
    "pay": frozenset({"payroll_admin", "hr_admin"}),
    "bank": frozenset({"payroll_admin"}),
    "identity": frozenset({"hr_admin"}),
    "health": frozenset({"hr_admin"}),
}
