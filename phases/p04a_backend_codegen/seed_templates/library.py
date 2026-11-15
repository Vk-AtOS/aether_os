"""
Seed template for library domain.
"""
import random
from datetime import datetime, timedelta, timezone
from models import Book, Member, Checkout, Reservation

async def seed_library(db_session):
    # 1. Books (Minimum 200)
    books = []
    categories = ["Fiction", "Non-Fiction", "Science", "History", "Biography", "Fantasy", "Mystery", "Philosophy"]
    for i in range(200):
        b = Book(
            title=f"The Great Book {i+1}",
            author=f"Author { (i % 20) + 1}",
            isbn=f"978-0-123456-{i:03d}",
            category=random.choice(categories)
        )
        books.append(b)
    db_session.add_all(books)
    await db_session.flush()

    # 2. Members (Minimum 50)
    members = []
    for i in range(50):
        m = Member(
            full_name=f"Library Member {i+1}",
            email=f"member{i+1}@library.org",
            joined_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 730))
        )
        members.append(m)
    db_session.add_all(members)
    await db_session.flush()

    # 3. Checkouts (Minimum 30)
    checkouts = []
    for i in range(30):
        c = Checkout(
            book_id=books[i % len(books)].id,
            member_id=members[i % len(members)].id,
            due_date=(datetime.now(timezone.utc) + timedelta(days=14)).date(),
            status="active"
        )
        checkouts.append(c)
    db_session.add_all(checkouts)
    await db_session.flush()

    # 4. Reservations (Minimum 10)
    for i in range(10):
        res = Reservation(
            book_id=books[(i + 50) % len(books)].id,
            member_id=members[i % len(members)].id,
            status="pending",
            reserved_at=datetime.now(timezone.utc)
        )
        db_session.add(res)
    
    await db_session.commit()
