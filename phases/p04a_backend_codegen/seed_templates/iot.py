"""
Seed template for iot domain.
"""
import random
from models import Device, DeviceGroup, Reading, Alert

async def seed_iot(db_session):
    # 1. Device Groups (Minimum 5)
    groups = [
        DeviceGroup(name="Warehouse A", description="Sensors in main warehouse"),
        DeviceGroup(name="Data Center", description="Temp/Humidity in DC"),
        DeviceGroup(name="Headquarters", description="Smart office controls"),
        DeviceGroup(name="Manufacturing", description="Factory floor sensors"),
        DeviceGroup(name="Logistics Hub", description="Trackers at hub"),
    ]
    db_session.add_all(groups)
    await db_session.flush()

    # 2. Devices (Minimum 20)
    devices = []
    for i in range(20):
        d = Device(
            name=f"Device-{100 + i}",
            type=random.choice(["temperature", "humidity", "motion", "pressure", "vibration"]),
            status="online",
            group_id=groups[i % len(groups)].id
        )
        devices.append(d)
    db_session.add_all(devices)
    await db_session.flush()

    # 3. Readings (Minimum 100)
    for i in range(100):
        r = Reading(
            device_id=devices[i % len(devices)].id,
            type=devices[i % len(devices)].type,
            value=round(random.uniform(10.0, 40.0), 2),
            timestamp="2024-06-01T12:00:00Z"
        )
        db_session.add(r)

    # 4. Alerts (Minimum 10)
    for i in range(10):
        a = Alert(
            device_id=devices[i % len(devices)].id,
            message=f"High {devices[i % len(devices)].type} detected!",
            severity=random.choice(["warning", "critical"]),
            timestamp="2024-06-01T13:00:00Z"
        )
        db_session.add(a)

    await db_session.commit()
