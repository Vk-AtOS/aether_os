"""
Seed template for ecommerce domain.
"""
from sqlalchemy import select, func
from models import User, Product, Category, Order, OrderItem

async def seed_ecommerce(db_session):
    # 1. Categories
    categories = [
        Category(name="Electronics", description="Gadgets and devices"),
        Category(name="Clothing", description="Apparel and fashion"),
        Category(name="Home", description="Furniture and decor"),
        Category(name="Books", description="Literature and educational"),
        Category(name="Beauty", description="Cosmetics and personal care"),
    ]
    db_session.add_all(categories)
    await db_session.flush()

    # 2. Products
    products = []
    for i in range(50):
        p = Product(
            name=f"Product {i+1}",
            description=f"High quality description for product {i+1}",
            price=19.99 + (i * 5),
            stock_quantity=100 - i,
            category_id=categories[i % len(categories)].id
        )
        products.append(p)
    db_session.add_all(products)
    await db_session.flush()

    # 3. Orders & Items
    for i in range(30):
        order = Order(
            customer_email=f"customer{i+1}@example.com",
            total_amount=100.0,
            status="delivered" if i % 2 == 0 else "shipped"
        )
        db_session.add(order)
        await db_session.flush()
        
        item = OrderItem(
            order_id=order.id,
            product_id=products[i % len(products)].id,
            quantity=2,
            unit_price=products[i % len(products)].price
        )
        db_session.add(item)
    
    await db_session.commit()
