"""
Seed template for crm domain.
"""
from models import Contact, Company, Deal

async def seed_crm(db_session):
    # 1. Companies
    companies = [
        Company(name="TechCorp", industry="Software", revenue=1000000),
        Company(name="GlobalLogistics", industry="Logistics", revenue=5000000),
        Company(name="InnovateAI", industry="AI", revenue=2000000),
    ]
    db_session.add_all(companies)
    await db_session.flush()

    # 2. Contacts
    contacts = []
    for i in range(20):
        c = Contact(
            first_name=f"First{i}",
            last_name=f"Last{i}",
            email=f"contact{i}@company{i%3}.com",
            company_id=companies[i % len(companies)].id
        )
        contacts.append(c)
    db_session.add_all(contacts)
    await db_session.flush()

    # 3. Deals
    for i in range(15):
        d = Deal(
            title=f"Big Deal {i+1}",
            amount=10000.0 * (i + 1),
            stage="qualified" if i % 3 == 0 else "closed_won",
            company_id=companies[i % len(companies)].id
        )
        db_session.add(d)
    
    await db_session.commit()
