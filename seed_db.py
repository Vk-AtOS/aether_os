import asyncio
import uuid
import os
from aether_os.core.db import get_session_factory, init_db, get_engine
from aether_os.core.models import Organisation, User, Run, MarketplaceProfile
from sqlalchemy import select, update
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_MARKETPLACE_TEMPLATES = [
    {
        "name": "CRM & Sales Pipeline",
        "base_domain": "crm",
        "description": "Full-featured CRM with contacts, deals, pipeline stages, activities, and email history. Includes lead scoring and conversion tracking.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a CRM system with:
  - Contact management (name, email, phone, company, tags, notes)
  - Deal/opportunity tracking with pipeline stages (lead, qualified, proposal, negotiation, closed_won, closed_lost)
  - Activity log (calls, emails, meetings) linked to contacts and deals
  - Lead scoring (0-100) based on engagement
  - Dashboard with pipeline value, conversion rates, and activity summary
  - Search and filter across all entities
project_name: CRM Sales Pipeline
language: python
entities:
  - Contact
  - Deal
  - Activity
  - PipelineStage
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "HR & Employee Management",
        "base_domain": "hr",
        "description": "Complete HR platform: employees, departments, leave requests, performance reviews, payroll records, and org chart.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build an HR management system with:
  - Employee profiles (personal info, role, department, hire date, salary band)
  - Department hierarchy with managers
  - Leave management (request, approve, balance tracking) for vacation/sick/personal
  - Performance review cycles with goals and ratings
  - Payroll records (gross, net, deductions) per pay period
  - Org chart endpoint returning tree structure
project_name: HR Employee Management
language: python
entities:
  - Employee
  - Department
  - LeaveRequest
  - PerformanceReview
  - PayrollRecord
features:
  - jwt_auth
  - role_based_access
  - pagination
  - audit_log
""",
    },
    {
        "name": "Inventory & Warehouse",
        "base_domain": "inventory",
        "description": "Warehouse management with products, stock locations, purchase orders, stock movements, and low-stock alerts.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build an inventory management system with:
  - Product catalog (SKU, name, description, category, unit cost, sell price)
  - Warehouse locations (aisle, rack, bin) with stock levels per location
  - Purchase orders with line items and receiving workflow (draft/ordered/partial/received)
  - Stock movements (inbound, outbound, transfer) with timestamps and reasons
  - Low-stock alerts when quantity falls below reorder threshold
  - Stock valuation report (FIFO cost method)
project_name: Inventory Warehouse
language: python
entities:
  - Product
  - Location
  - PurchaseOrder
  - PurchaseOrderLine
  - StockMovement
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "Project Management & Tasks",
        "base_domain": "project_management",
        "description": "Jira-style project tracker with projects, sprints, tasks, subtasks, comments, and time tracking.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a project management system with:
  - Projects with name, description, status (active/archived), and team members
  - Sprints with start/end dates and goals
  - Tasks with title, description, assignee, priority (low/medium/high/critical), status (todo/in_progress/review/done), story points
  - Subtasks linked to parent tasks
  - Comments on tasks with threading
  - Time tracking entries (hours logged per task per user)
  - Burndown data endpoint (story points remaining per day)
project_name: Project Management Tasks
language: python
entities:
  - Project
  - Sprint
  - Task
  - Subtask
  - Comment
  - TimeEntry
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "Healthcare Patient Records",
        "base_domain": "healthcare",
        "description": "HIPAA-aligned patient management: patients, appointments, clinical notes, prescriptions, and billing records.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a healthcare patient management system with:
  - Patient profiles (demographics, insurance info, emergency contacts)
  - Appointments (scheduling, status: scheduled/completed/cancelled/no_show)
  - Clinical notes (SOAP format: subjective, objective, assessment, plan) linked to appointments
  - Prescriptions (medication, dosage, frequency, start/end date, refills remaining)
  - Billing records (procedure codes, amounts, insurance claims, payment status)
  - Patient portal: upcoming appointments and prescription list
  - All data scoped to provider org for multi-tenant isolation
project_name: Healthcare Patient Records
language: python
entities:
  - Patient
  - Appointment
  - ClinicalNote
  - Prescription
  - BillingRecord
features:
  - jwt_auth
  - role_based_access
  - pagination
  - audit_log
  - org_isolation
""",
    },
    {
        "name": "E-Commerce Backend",
        "base_domain": "ecommerce",
        "description": "Headless e-commerce API: products, categories, cart, orders, payments, and inventory sync.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a headless e-commerce backend with:
  - Product catalog with variants (size, color), images (URLs), and SKU management
  - Category tree (nested, unlimited depth)
  - Shopping cart (add/remove/update quantities, cart total with discounts)
  - Order lifecycle (cart → checkout → payment_pending → confirmed → shipped → delivered → refunded)
  - Payment records (amount, method, transaction_id, status)
  - Inventory tracking: decrement on order confirm, restock on refund
  - Promo codes (fixed amount / percentage discount, usage limits)
  - Order history per customer with line items
project_name: E-Commerce Backend
language: python
entities:
  - Product
  - ProductVariant
  - Category
  - Cart
  - Order
  - OrderItem
  - Payment
  - PromoCode
features:
  - jwt_auth
  - pagination
  - search
""",
    },
    {
        "name": "Real Estate Listings",
        "base_domain": "real_estate",
        "description": "Property listing platform with agents, properties, viewings, offers, and document management.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a real estate listing management system with:
  - Agent profiles (license number, agency, specialties, commission rate)
  - Property listings (address, type: residential/commercial/land, bedrooms, bathrooms, area_sqft, asking_price, status: active/under_offer/sold)
  - Property images (multiple URLs per listing)
  - Viewing appointments (scheduled by agents with prospective buyers)
  - Offers (amount, conditions, expiry date, status: pending/accepted/rejected/expired)
  - Document attachments per listing (title deed, survey, inspection report)
  - Search/filter by location, price range, bedrooms, type
project_name: Real Estate Listings
language: python
entities:
  - Agent
  - Property
  - PropertyImage
  - Viewing
  - Offer
  - Document
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "Event & Booking System",
        "base_domain": "events",
        "description": "Event management with venues, events, ticket tiers, bookings, check-in, and capacity tracking.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build an event booking system with:
  - Venues (name, address, capacity, amenities)
  - Events (title, description, venue, start/end datetime, organizer, status: draft/published/cancelled)
  - Ticket tiers (name, price, quantity_total, quantity_sold, sale_start/end)
  - Bookings (ticket tier, quantity, buyer info, booking_reference, status: confirmed/cancelled/refunded)
  - QR check-in endpoint: mark booking as attended, prevent duplicates
  - Waitlist for sold-out tiers (auto-promote when cancellation frees a slot)
  - Event dashboard: attendance rate, revenue per tier, check-in count
project_name: Event Booking System
language: python
entities:
  - Venue
  - Event
  - TicketTier
  - Booking
  - Waitlist
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "Financial Expense Tracker",
        "base_domain": "finance",
        "description": "Personal and team finance tracker: accounts, transactions, budgets, recurring expenses, and reports.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a financial expense tracking system with:
  - Accounts (checking, savings, credit card, cash) with current balance
  - Transactions (date, amount, merchant, category, notes, account, type: income/expense/transfer)
  - Budget rules (category, monthly_limit, start_date) with real-time spend vs. budget
  - Recurring transactions (frequency: daily/weekly/monthly/yearly, auto-generate next occurrence)
  - Categories with icon and color (hierarchical: Food > Groceries / Dining Out)
  - Monthly summary report: income, expenses, savings rate, top spending categories
  - Multi-currency with exchange rate snapshot at transaction time
project_name: Financial Expense Tracker
language: python
entities:
  - Account
  - Transaction
  - Budget
  - RecurringTransaction
  - Category
features:
  - jwt_auth
  - pagination
  - search
  - audit_log
""",
    },
    {
        "name": "Learning Management System",
        "base_domain": "lms",
        "description": "Full LMS: courses, modules, lessons, quizzes, student progress, certificates, and instructor dashboard.",
        "price_usd": 0.0,
        "profile_yaml": """requirement: |
  Build a Learning Management System with:
  - Courses (title, description, instructor, price, difficulty: beginner/intermediate/advanced, category)
  - Modules (ordered sections within a course)
  - Lessons (video URL, text content, duration, module, order_index)
  - Quizzes (per lesson, multiple choice questions with correct answer and explanation)
  - Student enrollments with progress tracking (lessons completed, quiz scores, completion percentage)
  - Certificate generation (issue when 100% complete, store certificate_id and issue_date)
  - Instructor dashboard: enrollment count, completion rates, average quiz score per course
  - Student dashboard: enrolled courses, progress, certificates earned
project_name: Learning Management System
language: python
entities:
  - Course
  - Module
  - Lesson
  - Quiz
  - Question
  - Enrollment
  - Certificate
features:
  - jwt_auth
  - role_based_access
  - pagination
  - search
  - audit_log
""",
    },
]

async def seed():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from pathlib import Path
    
    # Use environment URL or local default
    url = os.environ.get("DATABASE_URL")
    if not url:
        db_path = Path("aether_os.db")
        url = f"sqlite+aiosqlite:///{db_path.resolve()}"
    
    if "postgresql" in url and "asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"DEBUG: seed_db.py using engine: {url}")
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # 1. Create default organization
        org_slug = "default"
        stmt = select(Organisation).where(Organisation.slug == org_slug)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()
        
        if not org:
            org = Organisation(
                id=str(uuid.uuid4()),
                name="Default Organisation",
                slug=org_slug,
                plan="enterprise",  # Admin org is enterprise
                autonomous_mode=True,  # Skip spec-review gate for seeded orgs
            )
            session.add(org)
            print(f"Created organization: {org.name} ({org.id})")
        else:
            print(f"Organization {org_slug} already exists.")

        # 2. Create/Update admin user
        admin_email = os.environ.get("AETHER_ADMIN_EMAIL", "admin@aetheros.ai")
        # INFRA-H2: standardised on AETHER_ADMIN_PASS (matches core/seed.py)
        admin_pass = os.environ.get("AETHER_ADMIN_PASS")
        if not admin_pass:
            raise RuntimeError(
                "AETHER_ADMIN_PASS environment variable must be set before seeding the database"
            )
        
        stmt = select(User).where(User.email == admin_email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=admin_email,
                password_hash=pwd_context.hash(admin_pass),
                role="owner"
            )
            session.add(user)
            print(f"Created admin user: {user.email}")
        else:
            user.password_hash = pwd_context.hash(admin_pass)
            user.org_id = org.id # ensure correct org
            print(f"Updated admin user {admin_email} password.")

        # 3. Update existing runs
        stmt = update(Run).where(Run.org_id == None).values(org_id=org.id)
        result = await session.execute(stmt)
        print(f"Updated {result.rowcount} existing runs with org_id.")

        # 4. Seed marketplace templates (skip if already seeded by name)
        seeded = 0
        for tmpl in _MARKETPLACE_TEMPLATES:
            exists = (await session.execute(
                select(MarketplaceProfile).where(MarketplaceProfile.name == tmpl["name"])
            )).scalar_one_or_none()
            if not exists:
                session.add(MarketplaceProfile(
                    id=str(uuid.uuid4()),
                    org_id=org.id,
                    name=tmpl["name"],
                    base_domain=tmpl["base_domain"],
                    description=tmpl["description"],
                    price_usd=tmpl["price_usd"],
                    profile_yaml=tmpl["profile_yaml"],
                    is_published=True,
                    usage_count=0,
                ))
                seeded += 1
        if seeded:
            print(f"Seeded {seeded} marketplace templates.")
        else:
            print("Marketplace templates already present — skipped.")

        await session.commit()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed())
