"""Golden examples — compact domain builders and bug-fix examples.

Imported by seed_golden_examples.py. Split from seed_golden_helpers.py to
keep both modules under the 600-line project limit.
"""
from __future__ import annotations
from seed_golden_helpers import _quick, _bug


def build_compact_domains():
    """Build marketplace, erp, government, and traditional_erp examples."""
    marketplace = _quick("marketplace", [
        ("Freelancer marketplace with project bidding, escrow, and milestone payments", "Project,Bid,Contract,Milestone"),
        ("Job board for tech companies with applicant tracking and interview scheduling", "JobPosting,Application,Interview,Offer"),
        ("Real estate listings with agent profiles, virtual tours, and mortgage calculator", "Listing,Agent,ViewingRequest,SavedListing"),
        ("Used car marketplace with inspection reports, price history, and financing", "CarListing,InspectionReport,Offer,FinancingRequest"),
        ("Food delivery platform with restaurant menus, order tracking, and driver app", "Restaurant,MenuItem,Order,Delivery"),
        ("Online tutoring marketplace with lesson booking, video sessions, and reviews", "Tutor,Lesson,Booking,Review"),
        ("Home services booking for cleaners, plumbers, and electricians", "ServiceProvider,Service,Booking,Review"),
        ("Event ticket marketplace with seat selection and transfer support", "Event,Ticket,Order,Transfer"),
        ("Vacation rental platform with availability calendar and host messaging", "Property,Booking,Review,Message"),
        ("B2B wholesale procurement with RFQ, bulk pricing, and supplier ratings", "Supplier,RfqRequest,Quote,PurchaseOrder"),
    ])
    erp = _quick("erp", [
        ("Inventory management with multi-warehouse, FIFO costing, and reorder alerts", "Item,Warehouse,StockLevel,PurchaseOrder"),
        ("Manufacturing orders with BOM, work centers, and production scheduling", "Product,BillOfMaterial,WorkOrder,WorkCenter"),
        ("Procurement system with vendor management, approval workflows, and 3-way matching", "Vendor,PurchaseOrder,GoodsReceipt,VendorInvoice"),
        ("Warehouse management with pick/pack/ship, barcode scanning, and location tracking", "Location,StockMove,PickingOrder,ShipmentLabel"),
        ("Quality control with inspection plans, non-conformance reports, and corrective actions", "InspectionPlan,InspectionResult,NonConformance,CorrectiveAction"),
        ("Fixed asset management with depreciation schedules and disposal tracking", "Asset,DepreciationSchedule,MaintenanceRecord,Disposal"),
        ("Fleet management with vehicle tracking, fuel logs, and maintenance scheduling", "Vehicle,FuelLog,MaintenanceJob,DriverAssignment"),
        ("Production planning with demand forecasting, MRP, and capacity planning", "ProductionPlan,MaterialRequirement,CapacityLoad,WorkOrder"),
        ("Supply chain visibility with multi-tier supplier tracking and risk scoring", "Supplier,SupplierTier,RiskScore,ShipmentTracking"),
        ("Maintenance management (CMMS) with preventive schedules and spare parts", "Equipment,MaintenanceSchedule,WorkOrder,SparePart"),
    ])
    government = _quick("government", [
        ("Building permit management with plan review, inspections, and certificate issuance", "PermitApplication,PlanReview,Inspection,Certificate"),
        ("Citizen services portal for utility billing, tax payments, and service requests", "Citizen,ServiceRequest,Invoice,Payment"),
        ("Grant management for disbursement tracking, milestone reporting, and audits", "GrantProgram,Application,Award,MilestoneReport"),
        ("License renewal portal for business, professional, and vehicle licenses", "LicenseType,LicenseHolder,RenewalApplication,Payment"),
        ("Public procurement with RFP publishing, bid submission, and award management", "Rfp,Bid,EvaluationScore,Contract"),
        ("Court case management with hearing scheduling, document filing, and judgments", "Case,Party,Hearing,Document"),
        ("Land registry with parcel records, ownership transfers, and encumbrances", "Parcel,Owner,Transfer,Encumbrance"),
        ("Social services case management for benefits, referrals, and outcomes tracking", "Client,CaseWorker,ServicePlan,Outcome"),
        ("Public health reporting with disease surveillance and outbreak tracking", "Disease,Report,Outbreak,ResponseAction"),
        ("Voter registration with address verification, polling place assignment, and audit", "Voter,PollingPlace,Registration,AuditLog"),
    ])
    traditional_erp = _quick("traditional_erp", [
        ("General ledger with chart of accounts, journal entries, and period close", "Account,JournalEntry,JournalLine,FiscalPeriod"),
        ("Accounts payable with vendor invoices, payment runs, and aging reports", "Vendor,VendorInvoice,PaymentRun,PaymentLine"),
        ("Accounts receivable with customer invoices, collections, and aging", "Customer,CustomerInvoice,Receipt,CollectionAction"),
        ("Payroll with salary grades, deductions, tax filing, and bank transfer", "Employee,PayRun,PaySlip,TaxFiling"),
        ("Fixed assets with depreciation, revaluations, and disposal accounting", "Asset,DepreciationRun,Revaluation,Disposal"),
        ("Project accounting with budgets, timesheets, and cost allocation", "Project,Budget,Timesheet,CostAllocation"),
        ("Bank reconciliation with statement import and matching rules", "BankStatement,BankLine,ReconciliationRule,MatchedEntry"),
        ("Budget planning with scenario modeling, approval, and variance tracking", "Budget,BudgetLine,Scenario,Variance"),
        ("Financial consolidation with intercompany eliminations and minority interest", "Entity,ConsolidationRun,IntercompanyElim,ConsolidatedReport"),
        ("Management reporting with KPI dashboards, drill-down, and scheduled delivery", "KpiMetric,Report,ReportSchedule,Dashboard"),
    ])
    return marketplace, erp, government, traditional_erp


def build_bug_examples():
    return [
        # RELATIVE_IMPORT (15)
        _bug(1,"RELATIVE_IMPORT","ImportError: attempted relative import with no known parent package","routers/crud.py","from .models import User, Product","from src.models import User, Product","App runs with PYTHONPATH=/app. src is a top-level package, not a sub-package."),
        _bug(2,"RELATIVE_IMPORT","ImportError: attempted relative import","routers/crud.py","from .schemas import UserCreate, UserOut","from src.schemas import UserCreate, UserOut","Use absolute imports everywhere. src/ is on PYTHONPATH."),
        _bug(3,"RELATIVE_IMPORT","ImportError","main.py","from .database import get_db, engine","from src.database import get_db, engine","main.py is loaded directly by uvicorn, relative imports have no parent."),
        _bug(4,"RELATIVE_IMPORT","ImportError: attempted relative import","services.py","from ..models import Order\nfrom ..database import get_db","from src.models import Order\nfrom src.database import get_db","Never use .. — use absolute path from src root."),
        _bug(5,"RELATIVE_IMPORT","ImportError","routers/crud.py","from . import schemas","from src import schemas","Relative dot-import of a module — use absolute."),
        _bug(6,"RELATIVE_IMPORT","ImportError: no known parent package","routers/crud.py","from..models import Product","from src.models import Product","Bedrock Nova variant: no space after from. Same fix."),
        _bug(7,"RELATIVE_IMPORT","ModuleNotFoundError","routers/auth.py","from .models import User\nfrom .utils import hash_password","from src.models import User\nfrom src.utils import hash_password","Auth router uses relative imports. Fix all to absolute."),
        _bug(8,"RELATIVE_IMPORT","ImportError","seed.py","from .models import Base, User, Product","from src.models import Base, User, Product","Seed script must use absolute imports when run standalone."),
        _bug(9,"RELATIVE_IMPORT","ImportError","routers/crud.py","from .schemas import (ItemCreate, ItemUpdate, ItemOut)","from src.schemas import (ItemCreate, ItemUpdate, ItemOut)","Multi-line relative import — fix prefix."),
        _bug(10,"RELATIVE_IMPORT","ImportError","routers/items.py","from .crud import create_item, get_items","from src.crud import create_item, get_items","CRUD helper functions imported relatively."),
        _bug(11,"RELATIVE_IMPORT","ImportError","services.py","from .models import Category\nfrom .schemas import CategoryBase","from src.models import Category\nfrom src.schemas import CategoryBase","Service layer relative import."),
        _bug(12,"RELATIVE_IMPORT","ImportError","dependencies.py","from .models import User\nfrom .database import get_db","from src.models import User\nfrom src.database import get_db","FastAPI dependencies file with relative imports."),
        _bug(13,"RELATIVE_IMPORT","ImportError","routers/admin.py","from ..models import User, Role\nfrom ..auth import require_admin","from src.models import User, Role\nfrom src.auth import require_admin","Double-dot relative imports — replace with absolute."),
        _bug(14,"RELATIVE_IMPORT","ImportError","tasks.py","from .models import Task\nfrom .database import AsyncSession","from src.models import Task\nfrom src.database import AsyncSession","Background task file using relative imports."),
        _bug(15,"RELATIVE_IMPORT","ImportError","routers/crud.py","from .models import *","from src.models import *","Star import with relative prefix."),
        # MISSING_AWAIT (10)
        _bug(16,"MISSING_AWAIT","TypeError: object SQLAlchemy... is a coroutine","routers/crud.py","result = db.execute(select(User))","result = await db.execute(select(User))","AsyncSession.execute() is a coroutine — must be awaited."),
        _bug(17,"MISSING_AWAIT","TypeError: coroutine was never awaited","routers/crud.py","db.commit()","await db.commit()","commit() on AsyncSession must be awaited."),
        _bug(18,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.refresh(obj)","await db.refresh(obj)","refresh() is async on AsyncSession."),
        _bug(19,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","result = db.scalar(select(User).where(User.id==id))","result = await db.scalar(select(User).where(User.id==id))","scalar() must be awaited on async session."),
        _bug(20,"MISSING_AWAIT","TypeError: coroutine","seed.py","db.execute(text('DELETE FROM users'))","await db.execute(text('DELETE FROM users'))","Async db.execute() in seed script must be awaited."),
        _bug(21,"MISSING_AWAIT","TypeError","routers/crud.py","rows = db.scalars(select(Product)).all()","rows = (await db.scalars(select(Product))).all()","scalars() is async — await before calling .all()."),
        _bug(22,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.delete(obj)\ndb.commit()","await db.delete(obj)\nawait db.commit()","Both delete() and commit() need await on AsyncSession."),
        _bug(23,"MISSING_AWAIT","TypeError: coroutine","routers/crud.py","db.add(new_user)\ndb.commit()\ndb.refresh(new_user)","db.add(new_user)\nawait db.commit()\nawait db.refresh(new_user)","add() is sync but commit() and refresh() are async."),
        _bug(24,"MISSING_AWAIT","TypeError","routers/crud.py","result = db.execute(update(Order).where(Order.id==id).values(status='paid'))","result = await db.execute(update(Order).where(Order.id==id).values(status='paid'))","UPDATE statement execute() must be awaited."),
        _bug(25,"MISSING_AWAIT","RuntimeError: coroutine never awaited","routers/crud.py","count = db.scalar(select(func.count()).select_from(User))","count = await db.scalar(select(func.count()).select_from(User))","Count query scalar() must be awaited."),
        # SEED_UNIQUENESS (10)
        _bug(26,"SEED_UNIQUENESS","sqlalchemy.exc.IntegrityError: UNIQUE constraint failed: users.email","seed.py","for i in range(20):\n    db.add(User(email='admin@example.com', name=f'User {i}'))","for i in range(20):\n    db.add(User(email=f'user_{i+1}@example.com', name=f'User {i+1}'))","Every seed row needs a unique email. Use f-string with index."),
        _bug(27,"SEED_UNIQUENESS","IntegrityError: UNIQUE constraint failed: users.username","seed.py","users = [User(username='admin') for _ in range(10)]","users = [User(username=f'user_{i+1}') for i in range(10)]","Username must be unique per row."),
        _bug(28,"SEED_UNIQUENESS","IntegrityError: UNIQUE constraint failed: products.slug","seed.py","products = [Product(slug='product-slug') for i in range(20)]","products = [Product(slug=f'product-{i+1}') for i in range(20)]","Slug must be unique — append index."),
        _bug(29,"SEED_UNIQUENESS","IntegrityError UNIQUE: items.sku","seed.py","items = [Item(sku='ITEM-001', name=f'Item {i}') for i in range(10)]","items = [Item(sku=f'ITEM-{i+1:03d}', name=f'Item {i+1}') for i in range(10)]","SKU must be unique across all seed items."),
        _bug(30,"SEED_UNIQUENESS","IntegrityError: UNIQUE phone","seed.py","contacts = [Contact(phone='+1555000001') for i in range(5)]","contacts = [Contact(phone=f'+155500000{i+1}') for i in range(5)]","Phone numbers must differ per seed record."),
        _bug(31,"SEED_UNIQUENESS","IntegrityError UNIQUE: organizations.slug","seed.py","orgs = [Org(slug='my-org') for _ in range(3)]","orgs = [Org(slug=f'org-{i+1}') for i in range(3)]","Org slug must be unique."),
        _bug(32,"SEED_UNIQUENESS","IntegrityError UNIQUE: api_keys.key_hash","seed.py","keys = [ApiKey(key_hash='abc123') for _ in range(5)]","import secrets\nkeys = [ApiKey(key_hash=secrets.token_hex(32)) for _ in range(5)]","Generate random unique tokens for API key seeds."),
        _bug(33,"SEED_UNIQUENESS","IntegrityError UNIQUE: employees.employee_id","seed.py","emps = [Employee(employee_id='EMP001') for _ in range(10)]","emps = [Employee(employee_id=f'EMP{i+1:03d}') for i in range(10)]","Employee ID must be unique — use formatted index."),
        _bug(34,"SEED_UNIQUENESS","IntegrityError UNIQUE: invoices.number","seed.py","invoices = [Invoice(number='INV-001') for _ in range(5)]","invoices = [Invoice(number=f'INV-{i+1:04d}') for i in range(5)]","Invoice number must be unique per record."),
        _bug(35,"SEED_UNIQUENESS","IntegrityError UNIQUE: domains.domain_name","seed.py","tenants = [Tenant(domain='example.com') for _ in range(3)]","tenants = [Tenant(domain=f'tenant{i+1}.example.com') for i in range(3)]","Each tenant needs a unique subdomain."),
        # MISSING_AUTH (5)
        _bug(36,"MISSING_AUTH","Endpoint accessible without authentication","routers/crud.py","@router.delete('/{id}')\nasync def delete_item(id: int, db: AsyncSession = Depends(get_db)):\n    ...","@router.delete('/{id}')\nasync def delete_item(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):\n    ...","Delete endpoints must require authentication."),
        _bug(37,"MISSING_AUTH","No auth on PUT endpoint","routers/crud.py","@router.put('/{id}')\nasync def update_item(id: int, body: ItemUpdate, db=Depends(get_db)):","@router.put('/{id}')\nasync def update_item(id: int, body: ItemUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):","Update endpoints need auth dependency."),
        _bug(38,"MISSING_AUTH","POST endpoint missing auth","routers/crud.py","@router.post('/')\nasync def create_item(body: ItemCreate, db=Depends(get_db)):","@router.post('/')\nasync def create_item(body: ItemCreate, db=Depends(get_db), current_user=Depends(get_current_user)):","Create endpoints must be authenticated."),
        _bug(39,"MISSING_AUTH","Admin endpoint unprotected","routers/admin.py","@router.delete('/users/{id}')\nasync def admin_delete_user(id: int, db=Depends(get_db)):","@router.delete('/users/{id}')\nasync def admin_delete_user(id: int, db=Depends(get_db), current_user=Depends(require_admin)):","Admin endpoints need elevated auth check."),
        _bug(40,"MISSING_AUTH","Bulk operation unprotected","routers/crud.py","@router.post('/bulk-delete')\nasync def bulk_delete(ids: list[int], db=Depends(get_db)):","@router.post('/bulk-delete')\nasync def bulk_delete(ids: list[int], db=Depends(get_db), current_user=Depends(get_current_user)):","Bulk destructive operations require auth."),
        # SQLALCHEMY_TYPE (5)
        _bug(41,"SQLALCHEMY_TYPE","sqlalchemy.exc.ArgumentError: Could not determine join condition","models.py","class Product:\n    id: int\n    name: str\n    price: float","class Product(Base):\n    __tablename__ = 'products'\n    id = Column(Integer, primary_key=True)\n    name = Column(String(255), nullable=False)\n    price = Column(Numeric(10, 2), nullable=False)","Use SQLAlchemy Column types not Python type hints for model fields."),
        _bug(42,"SQLALCHEMY_TYPE","ArgumentError: Mapper could not assemble","models.py","class User(Base):\n    id = int\n    email = str\n    is_active = bool","class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n    email = Column(String(255), unique=True, nullable=False)\n    is_active = Column(Boolean, default=True)","Class attributes must be Column() instances."),
        _bug(43,"SQLALCHEMY_TYPE","TypeError: expected Column","models.py","class Order(Base):\n    total = float\n    status = str","class Order(Base):\n    __tablename__ = 'orders'\n    total = Column(Numeric(10, 2), nullable=False)\n    status = Column(String(50), default='pending')","Use Numeric for money, String for status fields."),
        _bug(44,"SQLALCHEMY_TYPE","ProgrammingError: column type","models.py","class Event(Base):\n    starts_at = datetime","class Event(Base):\n    __tablename__ = 'events'\n    starts_at = Column(DateTime(timezone=True), nullable=False)","datetime Python type → Column(DateTime(timezone=True))."),
        _bug(45,"SQLALCHEMY_TYPE","TypeError","models.py","class Tag(Base):\n    metadata = dict","class Tag(Base):\n    __tablename__ = 'tags'\n    extra_data = Column(JSON, nullable=True)","dict → Column(JSON). Also avoid 'metadata' as column name — it's reserved by SQLAlchemy."),
        # PYDANTIC_V2 (6)
        _bug(46,"PYDANTIC_V2","PydanticUserError: `validator` is removed in V2","schemas.py","from pydantic import BaseModel, validator\nclass UserCreate(BaseModel):\n    @validator('email')\n    def email_must_be_lowercase(cls, v):\n        return v.lower()","from pydantic import BaseModel, field_validator\nclass UserCreate(BaseModel):\n    @field_validator('email', mode='before')\n    @classmethod\n    def email_must_be_lowercase(cls, v):\n        return v.lower()","Pydantic v2: @validator → @field_validator with mode='before' and @classmethod."),
        _bug(47,"PYDANTIC_V2","PydanticUserError: `orm_mode` is removed","schemas.py","class UserOut(BaseModel):\n    class Config:\n        orm_mode = True","from pydantic import ConfigDict\nclass UserOut(BaseModel):\n    model_config = ConfigDict(from_attributes=True)","Pydantic v2: Config.orm_mode → model_config = ConfigDict(from_attributes=True)."),
        _bug(48,"PYDANTIC_V2","ValidationError: BaseModel.schema() removed","schemas.py","schema = UserCreate.schema()","schema = UserCreate.model_json_schema()","Pydantic v2: .schema() → .model_json_schema()."),
        _bug(49,"PYDANTIC_V2","TypeError: BaseModel.dict() removed","routers/crud.py","data = user.dict()","data = user.model_dump()","Pydantic v2: .dict() → .model_dump()."),
        _bug(50,"PYDANTIC_V2","AttributeError: parse_obj","routers/crud.py","user = UserOut.parse_obj(row.__dict__)","user = UserOut.model_validate(row)","Pydantic v2: .parse_obj() → .model_validate()."),
        _bug(51,"PYDANTIC_V2","PydanticUserError: root_validator removed","schemas.py","from pydantic import root_validator\n@root_validator\ndef check_dates(cls, values):\n    return values","from pydantic import model_validator\n@model_validator(mode='after')\ndef check_dates(self):\n    return self","Pydantic v2: root_validator → @model_validator(mode='after')."),
        # CORS + MISSING_COMMIT + DUPLICATE_ROUTER
        _bug(52,"CORS_CREDENTIALS","CORS error: Credentials not allowed with wildcard origin","main.py","app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True)","app.add_middleware(CORSMiddleware, allow_origins=['https://yourapp.com'], allow_credentials=True)","Browsers block credentials with allow_origins=['*']. List exact origins."),
        _bug(53,"CORS_CREDENTIALS","Access-Control-Allow-Origin cannot be *","main.py","CORSMiddleware(allow_origins=['*'], allow_credentials=True, allow_methods=['*'])","CORSMiddleware(allow_origins=['https://app.example.com'], allow_credentials=True, allow_methods=['GET','POST','PUT','DELETE'])","Specify exact origins and methods when allow_credentials=True."),
        _bug(54,"CORS_CREDENTIALS","CORS blocked","main.py","allow_origins=['*']\nallow_credentials=True","# wildcard + credentials is blocked by browsers.\nallow_origins=['https://frontend.example.com']","Choose: wildcard origins OR credentials, not both."),
        _bug(55,"MISSING_COMMIT","Object not persisted after add()","routers/crud.py","db.add(new_user)\nreturn new_user","db.add(new_user)\nawait db.commit()\nawait db.refresh(new_user)\nreturn new_user","Must commit and refresh to persist and get DB-generated fields."),
        _bug(56,"MISSING_COMMIT","Changes lost after session close","routers/crud.py","obj.status = 'paid'\ndb.add(obj)","obj.status = 'paid'\ndb.add(obj)\nawait db.commit()\nawait db.refresh(obj)","Updates need commit() to be persisted to the database."),
        _bug(57,"MISSING_COMMIT","IntegrityError on next request","routers/crud.py","for item in items:\n    db.add(item)","for item in items:\n    db.add(item)\nawait db.commit()","Bulk adds need a single commit after the loop."),
        _bug(58,"DUPLICATE_ROUTER","APIRouter already included","main.py","app.include_router(users_router, prefix='/api')\napp.include_router(users_router, prefix='/api')","app.include_router(users_router, prefix='/api')","Duplicate include_router causes duplicate routes and potential middleware issues."),
        _bug(59,"DUPLICATE_ROUTER","Duplicate routes registered","main.py","app.include_router(items_router)\napp.include_router(items_router)","app.include_router(items_router)","Search for all app.include_router() calls and ensure each router appears once."),
        _bug(60,"DUPLICATE_ROUTER","422 on second call only","main.py","routers = [users_router, items_router, users_router]\nfor r in routers:\n    app.include_router(r)","routers = [users_router, items_router]\nfor r in routers:\n    app.include_router(r)","Deduplicate the routers list before iterating."),
    ]
