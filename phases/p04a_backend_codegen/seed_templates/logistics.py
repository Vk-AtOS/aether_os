"""
Seed template for logistics domain.
"""
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from models import User, Shipment, Driver, Route, DeliveryStop

async def seed_logistics(db_session):
    # 1. Drivers (Minimum 10)
    drivers = []
    names = ["Joe", "Sam", "Ann", "Bob", "Eve", "Dan", "Zoe", "Ray", "Kim", "Leo", "Mia", "Tom"]
    for i, name in enumerate(names):
        d = Driver(
            full_name=f"Driver {name}",
            license_number=f"L-{10000 + i}",
            phone=f"555-010{i}",
            status=random.choice(["available", "busy", "off-duty"])
        )
        drivers.append(d)
    db_session.add_all(drivers)
    await db_session.flush()

    # 2. Shipments (Minimum 30)
    shipments = []
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose"]
    for i in range(30):
        s = Shipment(
            tracking_number=f"TRK-{1000 + i}",
            origin=random.choice(cities),
            destination=random.choice(cities),
            weight=random.uniform(5.0, 500.0),
            status=random.choice(["pending", "shipped", "in-transit", "delivered", "cancelled"]),
            created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
        )
        shipments.append(s)
    db_session.add_all(shipments)
    await db_session.flush()

    # 3. Routes (Minimum 5)
    routes = []
    for i in range(5):
        r = Route(
            name=f"Route {chr(65+i)}",
            driver_id=drivers[i % len(drivers)].id,
            vehicle_id=1,
            start_time=datetime.now(timezone.utc) + timedelta(hours=i*2)
        )
        routes.append(r)
    db_session.add_all(routes)
    await db_session.flush()

    # 4. Delivery Stops (Minimum 20)
    stops = []
    for i in range(20):
        stop = DeliveryStop(
            route_id=routes[i % len(routes)].id,
            shipment_id=shipments[i % len(shipments)].id,
            stop_order=i // 5,
            address=f"{100 + i} Main St, {random.choice(cities)}",
            status=random.choice(["scheduled", "arrived", "completed", "skipped"])
        )
        stops.append(stop)
    db_session.add_all(stops)
    
    await db_session.commit()
