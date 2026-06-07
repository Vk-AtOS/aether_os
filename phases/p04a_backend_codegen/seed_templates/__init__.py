"""
Seed templates for domain-specific demo data.
Each function seed_{domain}(db_session) must:
1. Insert records in FK-correct order (parents before children).
2. Use realistic, domain-appropriate names.
3. Be idempotent.
"""
from sqlalchemy import select, func
from models import User

# Realistic seed utilities
_NAMES = ["Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Heidi"]
_RESTAURANTS = ["Burger Haven", "Pizza Palace", "Sushi Spot"]

async def seed_restaurant(db_session):
    # Example for Restaurant domain
    pass

async def seed_healthcare(db_session):
    # Example for Healthcare domain
    pass

async def seed_ecommerce(db_session):
    # Example for Ecommerce domain
    pass
