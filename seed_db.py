import asyncio
import uuid
import os
from aether_os.core.db import get_session_factory, init_db, get_engine
from aether_os.core.models import Organisation, User, Run
from sqlalchemy import select, update
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def seed():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from pathlib import Path
    
    # Use environment URL or local default
    url = os.environ.get("DATABASE_URL")
    if not url:
        db_path = Path("aether_os.db")
        url = f"sqlite+aiosqlite:///{db_path.resolve()}"
    
    if "postgresql" in url and "asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"DEBUG: seed_db.py using engine: {url}")
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # 1. Create default organization
        org_slug = "default"
        stmt = select(Organisation).where(Organisation.slug == org_slug)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()
        
        if not org:
            org = Organisation(
                id=str(uuid.uuid4()),
                name="Default Organisation",
                slug=org_slug,
                plan="enterprise"  # Admin org is enterprise
            )
            session.add(org)
            print(f"Created organization: {org.name} ({org.id})")
        else:
            print(f"Organization {org_slug} already exists.")

        # 2. Create/Update admin user
        admin_email = os.environ.get("AETHER_ADMIN_EMAIL", "admin@aetheros.ai")
        admin_pass = os.environ.get("AETHER_ADMIN_PASSWORD")
        if not admin_pass:
            raise RuntimeError(
                "AETHER_ADMIN_PASSWORD environment variable must be set before seeding the database"
            )
        
        stmt = select(User).where(User.email == admin_email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=admin_email,
                password_hash=pwd_context.hash(admin_pass),
                role="owner"
            )
            session.add(user)
            print(f"Created admin user: {user.email}")
        else:
            user.password_hash = pwd_context.hash(admin_pass)
            user.org_id = org.id # ensure correct org
            print(f"Updated admin user {admin_email} password.")

        # 3. Update existing runs
        stmt = update(Run).where(Run.org_id == None).values(org_id=org.id)
        result = await session.execute(stmt)
        print(f"Updated {result.rowcount} existing runs with org_id.")

        await session.commit()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed())
