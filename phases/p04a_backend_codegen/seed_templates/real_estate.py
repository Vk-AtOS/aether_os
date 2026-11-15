"""
Seed template for real_estate domain.
"""
from models import Property, Tenant, Lease

async def seed_real_estate(db_session):
    # 1. Properties
    properties = []
    for i in range(20):
        prop = Property(
            address=f"{100 + i} Oak Street",
            city="New York",
            type="Apartment" if i % 2 == 0 else "House",
            price=2000.0 + (i * 100),
            status="available" if i % 5 == 0 else "leased"
        )
        properties.append(prop)
    db_session.add_all(properties)
    await db_session.flush()

    # 2. Tenants
    tenants = []
    for i in range(15):
        t = Tenant(
            full_name=f"Tenant {i+1}",
            email=f"tenant{i+1}@example.com",
            phone=f"555-02{i:02d}"
        )
        tenants.append(t)
    db_session.add_all(tenants)
    await db_session.flush()

    # 3. Leases (FK to Property and Tenant)
    for i in range(10):
        lease = Lease(
            property_id=properties[i].id,
            tenant_id=tenants[i % len(tenants)].id,
            start_date="2024-01-01",
            end_date="2024-12-31",
            monthly_rent=properties[i].price
        )
        db_session.add(lease)
    
    await db_session.commit()
