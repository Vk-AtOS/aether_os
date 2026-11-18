"""KAN-131: plugins, learning patterns, feedback and golden builds have unique keys; races resolve."""
import asyncio
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from aether_os.core.db import get_session_factory
from aether_os.core.learning.golden_retriever import record_feedback
from aether_os.core.models import BuildFeedback, GoldenBuild, InstalledPluginRecord, Run, UserLearningPattern
from aether_os.core.services.learning_service import upsert_pattern


def run(coro):
    return asyncio.run(coro)


def _insert_twice(make):
    async def go():
        async with get_session_factory()() as s:
            s.add(make())
            await s.commit()
        with pytest.raises(IntegrityError):
            async with get_session_factory()() as s:
                s.add(make())
                await s.commit()
    run(go())


def test_database_refuses_duplicates(gw):
    org = gw.register("uniq").org_id
    _insert_twice(lambda: InstalledPluginRecord(id=str(uuid.uuid4()), org_id=org, plugin_id="slack"))
    _insert_twice(lambda: GoldenBuild(id=str(uuid.uuid4()), run_id="run-g", org_id=org, domain="x", project_name="p"))


def test_same_user_rating_a_run_twice_replaces_the_first(gw):
    u = gw.register("rater")
    rid = str(uuid.uuid4())

    async def go():
        async with get_session_factory()() as s:
            s.add(Run(id=rid, org_id=u.org_id, status="completed"))
            await s.commit()
        for rating in (5, 2):
            async with get_session_factory()() as s:
                await record_feedback(rid, u.org_id, "user-1", rating, ["t"], "c", s)
        async with get_session_factory()() as s:
            from sqlalchemy import select
            rows = (await s.execute(select(BuildFeedback).where(BuildFeedback.run_id == rid))).scalars().all()
            return [r.rating for r in rows]
    assert run(go()) == [2]


def test_concurrent_first_observations_of_a_pattern_do_not_crash_or_duplicate(gw):
    u = gw.register("pat")

    async def one():
        async with get_session_factory()() as s:
            await upsert_pattern(u.org_id, u.user_id, "naming_convention", "k", {"v": 1}, "r1", s)

    async def go():
        await asyncio.gather(one(), one(), one())
        async with get_session_factory()() as s:
            from sqlalchemy import select
            return len((await s.execute(select(UserLearningPattern).where(UserLearningPattern.org_id == u.org_id))).scalars().all())
    assert run(go()) == 1
