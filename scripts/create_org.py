import asyncio
import uuid
import argparse
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.db import get_session_factory, init_db
from core.models import Organisation, User
from sqlalchemy import select
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_org(email, password, org_name, plan):
    # Ensure tables exist
    await init_db()
    session_factory = get_session_factory()
    
    async with session_factory() as session:
        # Check if org exists
        slug = org_name.lower().replace(" ", "-")
        stmt = select(Organisation).where(Organisation.slug == slug)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            print(f"Error: Organisation with slug '{slug}' already exists.")
            return

        # Check if user exists
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
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
            password_hash=pwd_context.hash(password),
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
    
    args = parser.parse_args()
    
    # Set default AETHER_SECRET_KEY if not set to avoid errors in imports if any
    if "AETHER_SECRET_KEY" not in os.environ:
        os.environ["AETHER_SECRET_KEY"] = "management-script-key-placeholder"

    asyncio.run(create_org(args.email, args.password, args.org_name, args.plan))
