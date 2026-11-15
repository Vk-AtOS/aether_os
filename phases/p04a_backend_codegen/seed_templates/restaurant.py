"""
Seed template for Restaurant domain.
"""
from models import Restaurant, MenuItem, Order, User

async def seed_restaurant(db_session):
    # 1. Users (Staff)
    staff = []
    for i in range(5):
        u = User(email=f"staff{i+1}@quickbite.ie", password_hash="hashed", role="admin" if i == 0 else "staff")
        staff.append(u)
    db_session.add_all(staff)
    await db_session.flush()

    # 2. Restaurants
    restaurants = [
        Restaurant(name="Dublin Burger Co", address="12 O'Connell St"),
        Restaurant(name="Temple Bar Pizza", address="5 Fleet St"),
        Restaurant(name="Sushi Zen", address="22 Grafton St"),
    ]
    db_session.add_all(restaurants)
    await db_session.flush()

    # 3. Menu Items (FK to Restaurant)
    items = []
    for i in range(30):
        item = MenuItem(
            name=f"Menu Item {i+1}", 
            price=10.0 + (i % 10), 
            restaurant_id=restaurants[i % len(restaurants)].id
        )
        items.append(item)
    db_session.add_all(items)
    await db_session.flush()

    # 4. Orders
    for i in range(20):
        order = Order(
            customer_email=f"customer{i+1}@example.com", 
            status="delivered" if i % 2 == 0 else "placed",
            restaurant_id=restaurants[i % len(restaurants)].id
        )
        db_session.add(order)
    
    await db_session.commit()
