"""
Seed template for gym_fitness domain.
"""
import random
from datetime import datetime, timedelta, timezone
from models import Member, Trainer, Class, Booking

async def seed_gym_fitness(db_session):
    # 1. Trainers (Minimum 10)
    trainers = []
    specialties = ["Bodybuilding", "Aerobics", "Yoga", "CrossFit", "Zumba", "Pilates", "HIIT", "Spin", "Boxing", "Swimming"]
    names = ["Arnold", "Jane", "Yogi", "Chris", "Sarah", "Mike", "Emily", "David", "Laura", "Kevin"]
    for i, name in enumerate(names):
        t = Trainer(
            full_name=f"{name} {random.choice(['S.', 'F.', 'B.', 'H.', 'W.', 'M.'])}",
            specialty=specialties[i % len(specialties)],
            bio=f"Certified {specialties[i % len(specialties)]} expert with {random.randint(2, 20)} years of experience.",
            phone=f"555-020{i}"
        )
        trainers.append(t)
    db_session.add_all(trainers)
    await db_session.flush()

    # 2. Members (Minimum 40)
    members = []
    for i in range(40):
        m = Member(
            full_name=f"Member {i+1}",
            email=f"member{i+1}@gym.com",
            phone=f"555-030{i}",
            status=random.choice(["active", "active", "active", "suspended", "expired"]),
            joined_at=datetime.now(timezone.utc) - timedelta(days=random.randint(30, 365))
        )
        members.append(m)
    db_session.add_all(members)
    await db_session.flush()

    # 3. Classes (Minimum 20)
    classes = []
    for i in range(20):
        c = Class(
            name=f"{random.choice(specialties)} Session {i+1}",
            trainer_id=trainers[i % len(trainers)].id,
            start_time=datetime.now(timezone.utc).replace(hour=8, minute=0) + timedelta(hours=i),
            duration_minutes=random.choice([45, 60, 90]),
            capacity=random.randint(10, 30),
            room=f"Room {random.randint(1, 4)}"
        )
        classes.append(c)
    db_session.add_all(classes)
    await db_session.flush()

    # 4. Bookings (Minimum 200)
    bookings = []
    for i in range(200):
        b = Booking(
            member_id=members[i % len(members)].id,
            class_id=classes[i % len(classes)].id,
            status=random.choice(["confirmed", "confirmed", "confirmed", "attended", "cancelled"]),
            booked_at=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 14))
        )
        bookings.append(b)
    db_session.add_all(bookings)
    
    await db_session.commit()
