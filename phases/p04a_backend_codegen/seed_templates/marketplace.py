"""
Seed template for marketplace domain.
"""
import random
from sqlalchemy import select, func
from models import User, Seller, Product, Buyer, Order, Review

async def seed_marketplace(db_session):
    # 1. Sellers (Minimum 30)
    sellers = []
    for i in range(30):
        s = Seller(
            shop_name=f"Shop {i+1}",
            rating=round(random.uniform(3.5, 5.0), 1),
            description=f"Premium seller of quality goods since {2010 + (i % 14)}."
        )
        sellers.append(s)
    db_session.add_all(sellers)
    await db_session.flush()

    # 2. Products (Minimum 100)
    products = []
    categories = ["Electronics", "Fashion", "Home", "Garden", "Toys", "Books", "Sports"]
    for i in range(100):
        p = Product(
            name=f"Product {i+1}",
            price=round(random.uniform(10.0, 1000.0), 2),
            seller_id=sellers[i % len(sellers)].id,
            category=random.choice(categories),
            stock=random.randint(0, 100)
        )
        products.append(p)
    db_session.add_all(products)
    await db_session.flush()

    # 3. Buyers (Minimum 40)
    buyers = []
    for i in range(40):
        b = Buyer(
            full_name=f"Buyer {i+1}",
            email=f"buyer{i+1}@example.com"
        )
        buyers.append(b)
    db_session.add_all(buyers)
    await db_session.flush()

    # 4. Orders (Minimum 50)
    orders = []
    for i in range(50):
        o = Order(
            buyer_id=buyers[i % len(buyers)].id,
            total_amount=round(random.uniform(20.0, 500.0), 2),
            status=random.choice(["pending", "processing", "shipped", "completed", "cancelled"])
        )
        orders.append(o)
    db_session.add_all(orders)
    await db_session.flush()

    # 5. Reviews (Minimum 20)
    for i in range(20):
        rev = Review(
            product_id=products[i % len(products)].id,
            buyer_id=buyers[i % len(buyers)].id,
            rating=random.randint(1, 5),
            comment=random.choice(["Great product!", "Fast shipping", "Good quality", "As described", "Highly recommend"]),
        )
        db_session.add(rev)
    
    await db_session.commit()
