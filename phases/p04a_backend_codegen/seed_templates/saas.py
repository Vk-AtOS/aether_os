"""
Seed template for saas domain.
"""
from models import User, Organization, SubscriptionPlan

async def seed_saas(db_session):
    # 1. Plans
    plans = [
        SubscriptionPlan(name="Free", price=0.0, features="Basic access"),
        SubscriptionPlan(name="Pro", price=29.0, features="Full access"),
        SubscriptionPlan(name="Enterprise", price=199.0, features="Custom support"),
    ]
    db_session.add_all(plans)
    await db_session.flush()

    # 2. Organizations
    orgs = []
    for i in range(10):
        o = Organization(
            name=f"Org {i+1}",
            plan_id=plans[i % len(plans)].id
        )
        orgs.append(o)
    db_session.add_all(orgs)
    await db_session.flush()

    # 3. Users
    for i in range(50):
        u = User(
            email=f"user{i+1}@org{i%10}.com",
            password_hash="hashed",
            role="user"
        )
        db_session.add(u)
    
    await db_session.commit()
