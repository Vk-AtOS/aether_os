"""
Seed template for food domain (Restaurant focus).
"""
import random
from models import Location, MenuItem, Order, Staff

async def seed_food(db_session):
    # 1. Locations (Minimum 3)
    locs = [
        Location(name="Downtown Bistro", address="123 Main St", phone="555-0001"),
        Location(name="Uptown Grill", address="456 High St", phone="555-0002"),
        Location(name="Seaside Cafe", address="789 Beach Rd", phone="555-0003"),
    ]
    db_session.add_all(locs)
    await db_session.flush()

    # 2. Staff (Minimum 5)
    staff_list = []
    roles = ["Manager", "Chef", "Waiter", "Host", "Bartender"]
    for i in range(5):
        s = Staff(
            full_name=f"Staff Member {i+1}",
            role=roles[i],
            location_id=locs[i % len(locs)].id
        )
        staff_list.append(s)
    db_session.add_all(staff_list)
    await db_session.flush()

    # 3. Menu Items (Minimum 30)
    menu_items = []
    categories = ["Appetizer", "Main Course", "Dessert", "Drink"]
    for i in range(30):
        item = MenuItem(
            name=f"Special Dish {i+1}",
            price=round(random.uniform(5.0, 45.0), 2),
            category=random.choice(categories),
            location_id=locs[i % len(locs)].id
        )
        menu_items.append(item)
    db_session.add_all(menu_items)
    await db_session.flush()

    # 4. Orders (Minimum 20)
    for i in range(20):
        o = Order(
            location_id=locs[i % len(locs)].id,
            total_amount=round(random.uniform(20.0, 150.0), 2),
            status=random.choice(["placed", "preparing", "ready", "delivered"]),
            table_number=random.randint(1, 20)
        )
        db_session.add(o)
    
    await db_session.commit()
