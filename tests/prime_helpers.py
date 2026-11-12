"""Shared fixtures for the Prime approval tests: real services, real ledger, an
isolated SQLite database. Only the network and Redis are replaced."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import update

import aether_os.core.db as db
from aether_os.core import pipeline_state
from aether_os.core.audit import chain
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.models import Organisation, Run, User, Webhook
from aether_os.prime import Action, AutonomyLevel, Delegation, DelegationRepository, Limits
from aether_os.prime import authz, executors
from aether_os.prime.approvals import ApprovalService
from aether_os.prime.models import PrimeDelegation, PrimeOrgLimits, PrimeRequest

ORG, OTHER_ORG = "org_a", "org_b"
# Roles as stored (Prime reads them from the users table, not from the token):
# alice owner (the absent grantor), bob admin (her deputy), carol admin, dave member.
ALICE, BOB, CAROL, DAVE, MALLORY = "alice", "bob", "carol", "dave", "mallory"
ROLES = {ALICE: "owner", BOB: "admin", CAROL: "admin", DAVE: "member", MALLORY: "owner"}
BOB_IDS = [BOB, "bob@a.test"]
SYSTEM = "system:api_key"
ADMIN = {"user_id": CAROL, "org_id": ORG, "role": "admin", "sub": "carol@a.test"}
OWNER = {"user_id": ALICE, "org_id": ORG, "role": "owner", "sub": "alice@a.test"}
DEPUTY = {"user_id": BOB, "org_id": ORG, "role": "admin", "sub": "Bob@A.test"}
MEMBER = {"user_id": DAVE, "org_id": ORG, "role": "member", "sub": "dave@a.test"}
OUTSIDER = {"user_id": MALLORY, "org_id": OTHER_ORG, "role": "owner", "sub": "mallory@b.test"}
API_KEY = {"sub": "api_key", "org_id": ORG, "role": "api"}


@pytest_asyncio.fixture
async def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/prime.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)

    async def no_redis():
        return None
    monkeypatch.setattr(pipeline_state, "get_redis", no_redis)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[
            t.__table__ for t in (AuditChainEntry, PrimeDelegation, PrimeRequest,
                                  PrimeOrgLimits, Organisation, User, Run, Webhook)]))
    async with db.get_session_factory()() as s:
        s.add_all([Organisation(id=o, name=o, slug=o) for o in (ORG, OTHER_ORG)])
        await s.flush()
        for uid, org in ((ALICE, ORG), (BOB, ORG), (CAROL, ORG), (DAVE, ORG), (MALLORY, OTHER_ORG)):
            s.add(User(id=uid, org_id=org, email=f"{uid}@{org[-1]}.test", password_hash="x",
                       role=ROLES[uid]))
        await s.commit()
    yield ApprovalService(DelegationRepository())
    await engine.dispose()


async def grant(autonomy=AutonomyLevel.ACT_WITH_APPROVAL, **kw) -> Delegation:
    now = datetime.now(timezone.utc)
    d = Delegation(**{**dict(
        grantor=ALICE, deputy="bob@a.test", autonomy=autonomy,
        scope={"leave.approve", "invoice.approve", "run.spec.approve"},
        limits=Limits(max_amount=Decimal("1000"), currency="INR"),
        valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=2)), **kw})
    await DelegationRepository().add(d, org_id=ORG)
    return d


def act(type_="leave.approve", requested_by=SYSTEM, **kw) -> Action:
    return Action(type=type_, on_behalf_of=ALICE, requested_by=requested_by, **kw)


async def actions() -> list:
    return [e["action"] for e in await chain.read_entries(limit=1000)]


async def set_row(request_id: str, **values) -> None:
    async with db.get_session_factory()() as s:
        await s.execute(update(PrimeRequest).where(PrimeRequest.id == request_id).values(**values))
        await s.commit()


class Counting:
    """Test executor: counts calls and does what it is told."""
    name = "counting"

    def __init__(self, raises=None):
        self.calls, self.raises = [], raises

    async def describe(self, ctx):
        return "counts"

    async def execute(self, ctx):
        self.calls.append(ctx)
        if self.raises:
            raise self.raises
        return {"done": True}


@pytest.fixture
def counting(monkeypatch):
    ex = Counting()
    monkeypatch.setitem(executors.REGISTRY, ex.name, ex)
    monkeypatch.setitem(authz.EXECUTOR_AUTHORITY, ex.name, authz.ANY_MEMBER)
    return ex
