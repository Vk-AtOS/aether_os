"""
Seed template for events domain.
"""
import random
from datetime import datetime, timedelta, timezone
from models import Event, Attendee, Ticket, Venue

async def seed_events(db_session):
    # 1. Venues (Minimum 5)
    venues = [
        Venue(name="Convention Center", city="Dublin", capacity=5000),
        Venue(name="Grand Hall", city="London", capacity=1000),
        Venue(name="Outdoor Stadium", city="New York", capacity=20000),
        Venue(name="City Plaza", city="San Francisco", capacity=2500),
        Venue(name="Royal Theatre", city="Paris", capacity=1500),
    ]
    db_session.add_all(venues)
    await db_session.flush()

    # 2. Events (Minimum 10)
    events = []
    for i in range(10):
        ev = Event(
            title=f"Global Summit {i+1}",
            date=(datetime.now(timezone.utc) + timedelta(days=i*10)).date(),
            venue_id=venues[i % len(venues)].id,
            description=f"Annual conference on industry trends, part {i+1}."
        )
        events.append(ev)
    db_session.add_all(events)
    await db_session.flush()

    # 3. Attendees (Minimum 50)
    attendees = []
    for i in range(50):
        a = Attendee(
            full_name=f"Attendee {i+1}",
            email=f"attendee{i+1}@events-world.com"
        )
        attendees.append(a)
    db_session.add_all(attendees)
    await db_session.flush()

    # 4. Tickets (Minimum 30)
    for i in range(30):
        t = Ticket(
            event_id=events[i % len(events)].id,
            attendee_id=attendees[i % len(attendees)].id,
            price=random.choice([49.99, 99.99, 149.99, 299.99]),
            status="valid"
        )
        db_session.add(t)
    
    await db_session.commit()
