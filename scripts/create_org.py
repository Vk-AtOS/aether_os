import asyncio
import uuid
import argparse
import sys
import os
import bcrypt
from pathlib import Path

# Add project root to path
_root = Path(__file__).parent.parent
sys.path.append(str(_root))

# Load .env so DATABASE_URL matches the server
try:
    from dotenv import load_dotenv
    load_dotenv(_root / ".env")
except ImportError:
    pass

from core.db import get_session_factory, init_db
from core.models import Organisation, User
from sqlalchemy import select, delete


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def create_org(email, password, org_name, plan, force=False):
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        slug = org_name.lower().replace(" ", "-")

        if force:
            existing_user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if existing_user:
                await session.execute(delete(User).where(User.email == email))
                await session.execute(delete(Organisation).where(Organisation.id == existing_user.org_id))
            existing_org = (await session.execute(
                select(Organisation).where(Organisation.slug == slug)
            )).scalar_one_or_none()
            if existing_org:
                await session.execute(delete(User).where(User.org_id == existing_org.id))
                await session.execute(delete(Organisation).where(Organisation.id == existing_org.id))
            await session.commit()
        else:
            result = await session.execute(select(Organisation).where(Organisation.slug == slug))
            if result.scalar_one_or_none():
                print(f"Error: Organisation with slug '{slug}' already exists.")
                return

            result = await session.execute(select(User).where(User.email == email))
            if result.scalar_one_or_none():
                print(f"Error: User with email '{email}' already exists.")
                return

        org_id = str(uuid.uuid4())
        org = Organisation(
            id=org_id,
            name=org_name,
            slug=slug,
            plan=plan,
            trial_runs_used=0,
            trial_runs_limit=3
        )
        session.add(org)

        user = User(
            id=str(uuid.uuid4()),
            org_id=org_id,
            email=email,
            password_hash=_hash(password),
            role="owner"
        )
        session.add(user)

        await session.commit()
        print(f"Successfully created organisation and user.")
        print(f"Org Name: {org_name}")
        print(f"Org Slug: {slug}")
        print(f"Plan:     {plan}")
        print(f"Email:    {email}")
        print(f"Password: {password}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a fresh trial/pro/enterprise organisation.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--org-name", required=True)
    parser.add_argument("--plan", default="trial", choices=["trial", "pro", "enterprise"])
    parser.add_argument("--force", action="store_true",
                        help="Delete and recreate if user/org already exists")

    args = parser.parse_args()

    if "AETHER_SECRET_KEY" not in os.environ:
        raise SystemExit(
            "ERROR: AETHER_SECRET_KEY environment variable is not set.\n"
            "Set it to the same secret key used by your running AetherOS instance:\n"
            "  export AETHER_SECRET_KEY=<your-secret>\n"
            "  python scripts/create_org.py ..."
        )

    asyncio.run(create_org(args.email, args.password, args.org_name, args.plan, force=args.force))
