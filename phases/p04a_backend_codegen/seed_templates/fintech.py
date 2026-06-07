"""
Seed template for fintech domain.
"""
import random
from sqlalchemy import select, func
from models import User, Account, Transaction, Invoice, PaymentPlan

async def seed_fintech(db_session):
    # 1. Accounts (Minimum 20)
    accounts = []
    for i in range(20):
        acc = Account(
            account_number=f"ACC-{1000 + i}",
            balance=round(random.uniform(500.0, 50000.0), 2),
            currency="USD",
            type=random.choice(["savings", "checking", "investment", "credit"])
        )
        accounts.append(acc)
    db_session.add_all(accounts)
    await db_session.flush()

    # 2. Transactions (Minimum 100)
    for i in range(100):
        t = Transaction(
            account_id=accounts[i % len(accounts)].id,
            amount=round(random.uniform(1.0, 2000.0), 2),
            type=random.choice(["credit", "debit"]),
            description=f"Transaction Ref: {10000 + i}",
            date="2024-05-01"
        )
        db_session.add(t)

    # 3. Invoices (Minimum 10)
    invoices = []
    for i in range(10):
        inv = Invoice(
            account_id=accounts[i % len(accounts)].id,
            amount=round(random.uniform(100.0, 5000.0), 2),
            due_date="2024-06-30",
            status=random.choice(["pending", "paid", "overdue"])
        )
        invoices.append(inv)
    db_session.add_all(invoices)
    await db_session.flush()

    # 4. Payment Plans (Minimum 5)
    for i in range(5):
        plan = PaymentPlan(
            account_id=accounts[i % len(accounts)].id,
            total_amount=5000.0,
            installments=12,
            remaining_amount=5000.0 - (i * 400),
            status="active"
        )
        db_session.add(plan)
    
    await db_session.commit()
