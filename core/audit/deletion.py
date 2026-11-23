"""
AetherOS — erasing audit personal data when an account or organisation is deleted.

Deleting a person or an organisation must also erase what the ledger can reveal about
them (core/audit/subjects.py); this module is the one place that sequence lives.
Erasure is idempotent and ledgered (the events hold subject ids and kinds only, never a
raw email or IP). A failure raises ErasureIncomplete: callers report it, never swallow
it, and it can be retried:
  - account deletion erases BEFORE anonymising the user, so a failure leaves a live
    account the person can sign in to and delete again;
  - organisation deletion cannot (a deleted organisation refuses its own sign-ins), so
    the organisation is marked deleted first and `retry_pending` finishes any whose
    erasure did not complete (superadmin, POST /prime/ledger/erasure/retry).
Nothing logged here carries a raw value, only exception class names.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import select

from aether_os.core.audit import chain, subjects
from aether_os.core.audit.subjects import AuditErasure
from aether_os.core.db import get_session_factory
from aether_os.core.models import AuditLog, Organisation, User
from aether_os.prime import corrections, learned

logger = logging.getLogger(__name__)

_DELETED_EMAIL_SUFFIX = "@deleted.invalid"


class ErasureIncomplete(Exception):
    """Personal data in the ledger may still be readable; retry the erasure."""


async def org_erased(org_id: Any) -> bool:
    cid = chain.chain_id_for(org_id)
    async with get_session_factory()() as s:
        return (await s.execute(select(AuditErasure.id).where(
            AuditErasure.chain_id == cid, AuditErasure.kind.is_(None)).limit(1))).first() is not None


async def erase_organisation(org_id: str, by: str) -> Dict[str, Any]:
    try:
        await corrections.erase_org(org_id)    # approvers' corrections are the organisation's personal data too
        await learned.erase_org(org_id)        # what Prime learned about its people, their consents (KAN-228)
        return await subjects.erase_org(org_id, by)
    except Exception as e:  # reported to the caller as retryable, never skipped
        logger.error("audit erasure of org %s failed: %s", org_id, type(e).__name__)
        raise ErasureIncomplete(f"audit-data erasure failed ({type(e).__name__})") from e


async def erase_person(org_id: str, user_id: str, by: str) -> Dict[str, Any]:
    """Erase the user's email and the IPs they acted from, in their organisation.

    ponytail: an IP shared with colleagues (NAT) is hidden for them too; that errs on
    the side of privacy. Per-user IP links would need a subject column on audit_log.
    """
    async with get_session_factory()() as s:
        email = (await s.execute(select(User.email).where(
            User.id == user_id, User.org_id == org_id))).scalar()
        seen = (await s.execute(select(AuditLog.ip_address).distinct().where(
            AuditLog.org_id == org_id, AuditLog.user_id == user_id))).scalars().all()
    targets: List[str] = []
    if email and not email.endswith(_DELETED_EMAIL_SUFFIX):
        targets.append(email)
    targets += [v for v in seen if v and (v.startswith("sub_") or subjects.kind_of(v) == "ip")]
    erased = 0
    try:
        await corrections.erase_person(org_id, [user_id, *([email.lower()] if email else [])])
        await learned.erase_person(org_id, user_id)   # what Prime learned about them and their consents (KAN-228)
        for target in targets:
            try:
                await subjects.erase_subject(org_id, target, by)
                erased += 1
            except LookupError:  # a reference erased by an earlier attempt: already done
                continue
    except Exception as e:
        logger.error("audit erasure of a person in org %s failed: %s", org_id, type(e).__name__)
        raise ErasureIncomplete(f"audit-data erasure failed ({type(e).__name__})") from e
    return {"subjects_erased": erased}


async def pending_org_erasures() -> List[str]:
    """Deleted organisations whose audit personal data has not been erased yet."""
    async with get_session_factory()() as s:
        ids = (await s.execute(select(Organisation.id).where(Organisation.is_deleted.is_(True)))).scalars().all()
    out = []
    for org_id in ids:
        try:
            if not await org_erased(org_id):
                out.append(org_id)
        except ValueError as e:  # an id that cannot name a chain has no chain data
            logger.warning("org %s cannot name an audit chain: %s", org_id, e)
    return out


async def retry_pending(by: str) -> Dict[str, Any]:
    done, failed = [], []
    for org_id in await pending_org_erasures():
        try:
            await erase_organisation(org_id, by)
            done.append(org_id)
        except ErasureIncomplete:
            failed.append(org_id)
    return {"erased": done, "failed": failed}
