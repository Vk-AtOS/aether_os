"""
Seed 60 loadtest users + admin into PostgreSQL for load testing.
Run: python3 tests/load/seed_load_users.py
"""
import asyncio
import os
import sys
import pathlib

# Ensure aether_os is importable
_root = str(pathlib.Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).parent.parent.parent / ".env")

SEED_PASSWORD = "LoadTest@1234"
SEED_PREFIX = "loadtest_"
COUNT = 60


async def seed():
    from aether_os.core.db import init_db, get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import get_password_hash
    from sqlalchemy import select
    import uuid

    await init_db()
    sf = get_session_factory()

    pw_hash = get_password_hash(SEED_PASSWORD)

    async with sf() as session:
        seeded = 0
        for i in range(COUNT):
            email = f"{SEED_PREFIX}{i:04d}@loadtest.internal"
            existing = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if existing:
                continue

            slug = f"loadtest-{i:04d}"
            org = Organisation(
                id=str(uuid.uuid4()),
                name=f"LoadTest Org {i:04d}",
                slug=slug,
                plan="trial",
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=email,
                password_hash=pw_hash,
                role="owner",
                is_active=True,
            )
            session.add(user)
            seeded += 1

        # Ensure demo admin exists
        admin_email = "demo@aetheros.ai"
        admin_existing = (await session.execute(
            select(User).where(User.email == admin_email)
        )).scalar_one_or_none()
        if not admin_existing:
            admin_pw = get_password_hash("Admin@1234")
            admin_slug = "aetheros-demo"
            org = Organisation(
                id=str(uuid.uuid4()),
                name="AetherOS Demo",
                slug=admin_slug,
                plan="enterprise",
            )
            session.add(org)
            await session.flush()
            admin = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=admin_email,
                password_hash=admin_pw,
                role="admin",
                is_active=True,
            )
            session.add(admin)
            seeded += 1

        await session.commit()
        print(f"Seeded {seeded} users ({COUNT} load test + admin) into PostgreSQL")
        print(f"Existing users were skipped.")


if __name__ == "__main__":
    asyncio.run(seed())
