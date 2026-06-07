"""
Seed template for security domain.
"""
import random
from sqlalchemy import select, func
from models import User, Site, Camera, Alert, Operator

async def seed_security(db_session):
    # 1. Sites (Minimum 5)
    sites = [
        Site(name="Main Entrance", risk_level="high"),
        Site(name="Server Room", risk_level="critical"),
        Site(name="Office Floor", risk_level="low"),
        Site(name="Parking Lot", risk_level="medium"),
        Site(name="Warehouse", risk_level="high"),
    ]
    db_session.add_all(sites)
    await db_session.flush()

    # 2. Operators (Minimum 5)
    operators = []
    for i in range(5):
        op = Operator(
            full_name=f"Operator {i+1}",
            badge_id=f"B-{500 + i}",
            status="active"
        )
        operators.append(op)
    db_session.add_all(operators)
    await db_session.flush()

    # 3. Cameras (Minimum 20)
    cameras = []
    for i in range(20):
        c = Camera(
            name=f"CAM-{100 + i}",
            site_id=sites[i % len(sites)].id,
            status="online"
        )
        cameras.append(c)
    db_session.add_all(cameras)
    await db_session.flush()

    # 4. Alerts (Minimum 10)
    for i in range(10):
        a = Alert(
            type=random.choice(["motion_detected", "offline", "unauthorized_access"]),
            severity=random.choice(["low", "medium", "high", "critical"]),
            camera_id=cameras[i % len(cameras)].id,
            timestamp="2024-06-01T10:00:00Z"
        )
        db_session.add(a)

    await db_session.commit()
