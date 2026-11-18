"""
Seed template for hospitality domain.
"""
import random
from models import Room, Guest, Booking, Housekeeping

async def seed_hospitality(db_session):
    # 1. Rooms (Minimum 20)
    rooms = []
    for i in range(20):
        r = Room(
            number=f"{100 + i}",
            type=random.choice(["Single", "Double", "Deluxe", "Suite"]),
            price_per_night=round(random.uniform(80.0, 500.0), 2),
            status="available"
        )
        rooms.append(r)
    db_session.add_all(rooms)
    await db_session.flush()

    # 2. Guests (Minimum 15)
    guests = []
    for i in range(15):
        g = Guest(
            full_name=f"Guest {i+1}",
            email=f"guest{i+1}@traveler.com",
            phone=f"555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        )
        guests.append(g)
    db_session.add_all(guests)
    await db_session.flush()

    # 3. Bookings (Minimum 30)
    bookings = []
    for i in range(30):
        res = Booking(
            room_id=rooms[i % len(rooms)].id,
            guest_id=guests[i % len(guests)].id,
            check_in="2024-06-01",
            check_out="2024-06-05",
            status="confirmed"
        )
        bookings.append(res)
    db_session.add_all(bookings)
    await db_session.flush()

    # 4. Housekeeping (Minimum 5)
    for i in range(5):
        h = Housekeeping(
            room_id=rooms[i % len(rooms)].id,
            staff_name=f"Cleaner {i+1}",
            status="completed",
            last_cleaned="2024-06-01T09:00:00Z"
        )
        db_session.add(h)
    
    await db_session.commit()
