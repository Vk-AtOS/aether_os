"""HR proxy: POST /hr/{agent}/{method} -> Velaris POST /agents/{agent}/{method}, for the pairs in
gateway/velaris_hr_table.py and NO others (not a generic passthrough). Rules per row (role, typed confirmation,
timeout, body and answer caps, ledger of names only) live in gateway/velaris_proxy.py. Velaris still applies its
own allow-list and roles, and answers 202 for acts that wait for approval; that is passed through unchanged.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Body, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.velaris.roles import ADMIN_ROLES
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.velaris_hr_table import HR_ALLOW, HR_DEDICATED, HR_ROUTES  # noqa: F401  (re-exported)
from aether_os.gateway.velaris_proxy import build_router, identity

router = build_router("/hr", "/agents", HR_ROUTES, "velaris-hr")


@router.get("/allowlist")
async def allowlist(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The pairs this proxy will forward (lets the UI say 'not available' instead of guessing). `admin` lists the
    pairs that need the owner/admin role and `confirm` the typed word a destructive pair needs."""
    await identity(user, acting=False)
    return {"agents": {a: sorted(m) for a, m in sorted(HR_ALLOW.items())},
            "admin": sorted(f"{a}.{m}" for a, m in HR_DEDICATED),
            "confirm": {f"{r.path.strip('/').replace('/', '.')}": r.confirm for r in HR_ROUTES if r.confirm}}


# Which Velaris employee record each sign-in is (own leave, payslips, policies). Admin only: a member must never pick
# their own link, or they could read another person's pay. Registered BEFORE the generic table rows is not needed:
# these paths ("/links") do not collide with "/AGENT/method".
@router.get("/links")
async def links(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    who = await identity(user, acting=False)
    if who.org_role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can see employee links")
    async with get_session_factory()() as s:
        rows = (await s.execute(select(User.id, User.email, User.velaris_employee_id).where(
            User.org_id == who.org_id, User.deleted_at.is_(None)).order_by(User.email).limit(200))).all()
    return {"links": [{"user_id": r[0], "email": r[1], "employee_id": r[2]} for r in rows]}


@router.put("/links/{user_id}")
async def set_link(user_id: str, body: Dict[str, Any] = Body(...),
                   user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    who = await identity(user, acting=True)
    if who.org_role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can link employees")
    emp = body.get("employee_id")
    if emp is not None and not (isinstance(emp, str) and 0 < len(emp) <= 128 and emp.isprintable()):
        raise HTTPException(status_code=422, detail="employee_id is a short text, or null to unlink")
    try:
        async with get_session_factory()() as s:
            done = await s.execute(update(User).where(User.id == user_id, User.org_id == who.org_id)
                                   .values(velaris_employee_id=emp or None))
            if not done.rowcount:
                raise HTTPException(status_code=404, detail="No such user in this organisation")
            await s.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="That employee record is already linked to another sign-in") from None
    await audit_chain.append(actor=who.user_id, action="velaris.hr.link",
                             payload={"org_id": who.org_id, "target": user_id, "linked": bool(emp)})
    return {"user_id": user_id, "employee_id": emp or None}
