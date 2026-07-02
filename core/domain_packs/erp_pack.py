"""
ERP Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and seed patterns
for generating correct Human Resources / Enterprise Resource Planning backends
and frontends.
"""
from __future__ import annotations

from aether_os.core.domain_packs import (
    DomainPack,
    EntitySpec,
    IntegrationSpec,
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENTITIES = [
    EntitySpec(
        name="Department",
        description=(
            "Organizational unit. Employees belong to a Department. "
            "Departments may be nested via parent_id."
        ),
        typical_fields=[
            "id", "name", "code",
            "parent_id",  # nullable FK to self — department hierarchy
            "manager_id",  # nullable FK to Employee
            "budget",       # Numeric(14,2) — annual department budget
            "headcount",    # current headcount — computed or denormalized
            "location",
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["code"],
        fk_relationships=["parent_id -> Department.id"],  # self-referential
        compliance_fields=[],
        indexes=["code", "parent_id", "is_active"],
    ),
    EntitySpec(
        name="Employee",
        description=(
            "Core HR entity. Has a self-referential manager_id FK for the org chart. "
            "Salary is stored as Numeric(12,2) — never Float."
        ),
        typical_fields=[
            "id", "employee_id",  # EMP-{i:05d}
            "first_name", "last_name", "email", "phone",
            "department_id",
            "manager_id",   # nullable FK to Employee (self-referential)
            "job_title", "employment_type",  # full_time / part_time / contractor / intern
            "status",  # active / on_leave / terminated / probation
            "hire_date", "termination_date",  # nullable
            "salary",         # Numeric(12,2)
            "salary_currency",  # ISO 4217
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["employee_id", "email"],
        fk_relationships=[
            "department_id -> Department.id",
            "manager_id -> Employee.id",  # nullable self-referential FK
        ],
        compliance_fields=["salary"],  # sensitive — restrict API access
        indexes=["employee_id", "email", "department_id", "manager_id", "status"],
    ),
    EntitySpec(
        name="Project",
        description=(
            "Business project tracked in the ERP. Employees are assigned tasks "
            "within projects. Budget tracked against actual spend."
        ),
        typical_fields=[
            "id", "project_code",  # PRJ-{i:05d}
            "name", "description",
            "department_id", "owner_id",  # FK to Employee
            "status",  # planning / active / on_hold / completed / cancelled
            "priority",  # low / medium / high / critical
            "budget",          # Numeric(14,2)
            "actual_spend",    # Numeric(14,2) — updated from Task completions
            "start_date", "end_date",
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["project_code"],
        fk_relationships=[
            "department_id -> Department.id",
            "owner_id -> Employee.id",
        ],
        compliance_fields=[],
        indexes=["project_code", "department_id", "owner_id", "status"],
    ),
    EntitySpec(
        name="Task",
        description=(
            "Unit of work within a Project assigned to an Employee. "
            "Status progresses: todo -> in_progress -> review -> done."
        ),
        typical_fields=[
            "id", "task_reference",  # TSK-{i:06d}
            "project_id", "assignee_id",  # FK to Employee
            "created_by_id",  # FK to Employee
            "title", "description",
            "status",  # todo / in_progress / review / done / cancelled
            "priority",  # low / medium / high / critical
            "estimated_hours",  # Numeric(6,2)
            "actual_hours",     # Numeric(6,2)
            "due_date", "completed_at",
            "created_at", "updated_at",
        ],
        unique_fields=["task_reference"],
        fk_relationships=[
            "project_id -> Project.id",
            "assignee_id -> Employee.id",
            "created_by_id -> Employee.id",
        ],
        compliance_fields=[],
        indexes=["task_reference", "project_id", "assignee_id", "status", "due_date"],
    ),
    EntitySpec(
        name="Leave",
        description=(
            "Employee leave request. Requires manager approval. "
            "approval_status Enum prevents free-form strings."
        ),
        typical_fields=[
            "id", "reference_number",  # LV-{YYYY}-{i:06d}
            "employee_id",
            "approver_id",  # nullable FK to Employee (manager)
            "leave_type",  # annual / sick / maternity / paternity / unpaid / study
            "start_date", "end_date",
            "days_requested",  # Numeric(4,1) — supports half-days
            "approval_status",  # pending / approved / rejected / cancelled
            "approved_at",  # nullable
            "reason",
            "rejection_reason",  # nullable
            "created_at", "updated_at",
        ],
        unique_fields=["reference_number"],
        fk_relationships=[
            "employee_id -> Employee.id",
            "approver_id -> Employee.id",
        ],
        compliance_fields=[],
        indexes=["reference_number", "employee_id", "approver_id", "approval_status"],
    ),
    EntitySpec(
        name="Payroll",
        description=(
            "Immutable payroll record for an Employee in a pay period. "
            "Once processed, records must not be modified — only reversed via a new record."
        ),
        typical_fields=[
            "id", "payroll_reference",  # PAY-{YYYY}-{MM}-{i:05d}
            "employee_id",
            "period_start", "period_end",
            "gross_salary",    # Numeric(12,2)
            "deductions_json", # tax, insurance, pension breakdowns
            "net_salary",      # Numeric(12,2)
            "currency",        # ISO 4217 — USD, EUR, GBP, INR, AUD
            "vat_rate",        # Numeric(6,4) nullable — VAT/GST rate at time of payroll
            "vat_number",      # String nullable — employer VAT/GST registration number
            "is_processed",    # Boolean — True = immutable
            "processed_at",    # nullable DateTime
            "payment_method",  # bank_transfer / cheque / crypto
            "created_at",
            # No updated_at — payroll records are append-only
        ],
        unique_fields=["payroll_reference"],
        fk_relationships=["employee_id -> Employee.id"],
        compliance_fields=["gross_salary", "net_salary"],  # sensitive payroll data
        indexes=["payroll_reference", "employee_id", "period_start", "is_processed"],
    ),
    EntitySpec(
        name="Asset",
        description=(
            "Physical or digital asset tracked in the ERP. "
            "assigned_to FK links the asset to the current Employee holder."
        ),
        typical_fields=[
            "id", "asset_tag",   # AST-{i:06d}
            "name", "description",
            "asset_type",  # laptop / monitor / phone / vehicle / software_license / furniture
            "status",  # available / assigned / maintenance / retired / lost
            "assigned_to_id",   # nullable FK to Employee
            "department_id",    # nullable FK to Department
            "purchase_date", "warranty_expiry",
            "purchase_cost",    # Numeric(18,4) — stored with ISO 4217 currency
            "current_value",    # Numeric(18,4) — depreciated value
            "currency",         # ISO 4217 — e.g. USD, EUR, GBP
            "serial_number",
            "location",
            "created_at", "updated_at",
        ],
        unique_fields=["asset_tag", "serial_number"],
        fk_relationships=[
            "assigned_to_id -> Employee.id",  # nullable
            "department_id -> Department.id",
        ],
        compliance_fields=[],
        indexes=["asset_tag", "serial_number", "assigned_to_id", "status", "asset_type"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="sendgrid",
        purpose=(
            "Payroll slip delivery, leave approval/rejection emails, "
            "task assignment notifications, onboarding welcome emails"
        ),
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_payroll_slip",
            "send_leave_approval",
            "send_leave_rejection",
            "send_task_assigned",
            "send_onboarding_welcome",
            "send_contract_expiry_reminder",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # Org chart
    "Employee.manager_id MUST be a nullable FK to Employee.id (self-referential) — root employees (CEO) have manager_id=None.",
    "Department.parent_id MUST be a nullable FK to Department.id (self-referential) — enforce no circular parent references at application layer.",
    # Payroll immutability
    "Payroll records are IMMUTABLE after is_processed=True — implement an application-level guard that raises HTTP 403 on UPDATE/DELETE of processed payrolls.",
    "Payroll amounts (gross_salary, net_salary) MUST use Numeric(12,2) — never Float or int.",
    "To correct a processed payroll, create a new reversal record — never modify the original.",
    # Leave approval
    "Leave.approval_status MUST use an Enum: pending / approved / rejected / cancelled — never a free-form string.",
    "Leave approved_at MUST be set when approval_status transitions to 'approved' — validate in the service layer.",
    "Leave days_requested MUST be computed from (end_date - start_date) + 1 at creation; do not accept a raw client-supplied value without validation.",
    # Asset tracking
    "Asset.assigned_to_id is nullable — when an asset is unassigned, set to NULL rather than a sentinel value.",
    "Asset status MUST use an Enum: available / assigned / maintenance / retired / lost.",
    "Asset.asset_tag MUST follow format AST-{i:06d} and be unique.",
    # Salary privacy
    "Salary fields (gross_salary, net_salary, salary) MUST NOT be returned in list endpoints — expose in detail endpoints only, gated to HR and admin roles.",
    "Payroll slip emails MUST be sent to the employee's official email only — never CC third parties.",
    # Reference number formats
    "Employee ID MUST follow format EMP-{i:05d} and be unique.",
    "Project code MUST follow format PRJ-{i:05d} and be unique.",
    "Leave reference MUST follow format LV-{YYYY}-{i:06d} and be unique.",
    "Payroll reference MUST follow format PAY-{YYYY}-{MM}-{i:05d} and be unique.",
    "Task reference MUST follow format TSK-{i:06d} and be unique.",
    # Multi-currency and fiscal year
    "All monetary amounts stored as NUMERIC(18,4) — never float for payroll or asset values",
    "Multi-currency: store amounts with their ISO 4217 currency code; convert to base_currency for reporting only",
    "VAT/GST rate stored on each transaction — do not hardcode tax rates",
    "Fiscal year is configurable (not always Jan-Dec) — store fiscal_year_start_month as org setting",
    "Payroll records are immutable after status='processed' — no updates allowed",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "employee_id": "EMP-{i:05d}",
    "project_code": "PRJ-{i:05d}",
    "task_reference": "TSK-{i:06d}",
    "reference_number_leave": "LV-2026-{i:06d}",
    "payroll_reference": "PAY-2026-01-{i:05d}",
    "asset_tag": "AST-{i:06d}",
    "email": "employee_{i}@example.com",
    "phone": "+1555{i:07d}",
    "salary": "{3000 + i * 250}.00",
    "salary_currency": "USD|EUR|GBP|INR|AUD",
    # Multi-currency: Employee, Payroll, Asset all carry an ISO 4217 currency code
    "currency": "USD|EUR|GBP|INR|AUD",
    # VAT/GST fields on Payroll
    "vat_rate": "0.20|0.18|0.10|0.05|None",
    "vat_number": "GB123456789|IN29ABCDE1234F1ZS|None",
    "employment_type": "full_time|part_time|contractor|intern",
    "status_employee": "active|on_leave|terminated|probation",
    "leave_type": "annual|sick|maternity|unpaid|study",
    "approval_status": "pending|approved|rejected|cancelled",
    "asset_type": "laptop|monitor|phone|vehicle|software_license|furniture",
    "status_asset": "available|assigned|maintenance|retired",
    "department_code": "DEPT-{i:03d}",
    "job_title": "Software Engineer|Data Analyst|Product Manager|HR Specialist|DevOps Engineer|Finance Analyst|Marketing Manager|Sales Executive",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Self-referential FK: Employee.manager_id uses ForeignKey('employees.id', use_alter=True) with post_update=True in SQLAlchemy to avoid circular insert deadlocks.",
    "Org chart: implement a recursive CTE (WITH RECURSIVE) to fetch the full reporting hierarchy in a single query — avoid N+1 manager lookups.",
    "Payroll immutability: add an application-layer guard in the payroll service: if payroll.is_processed: raise HTTP 403 'Processed payroll records cannot be modified'.",
    "Leave balance: track leave entitlement per employee per year in a LeaveBalance model — deduct when leave is approved, restore when leave is cancelled.",
    "Salary access: implement an HR role check in get_current_user_with_role dependency — salary fields visible only to HR Manager and above.",
    "Asset lifecycle: implement asset assignment history via an AssetAssignment log table — track who held an asset and when.",
    "Payroll computation: gross_salary = base_salary + allowances; net_salary = gross_salary - deductions (tax + insurance + pension) — store deductions as JSON breakdown.",
    "Background tasks: send payroll slip email via FastAPI BackgroundTasks after setting is_processed=True — never block the API response.",
    "Multi-currency: use a CurrencyRate lookup table with (from_currency, to_currency, rate, effective_date)",
    "Fiscal year: store FiscalYear entity with (org_id, year_label, start_date, end_date)",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

ERP_PACK = DomainPack(
    domain="erp",
    display_name="ERP / Human Resources",
    description=(
        "Enterprise Resource Planning platform supporting employees, departments, "
        "projects, tasks, leave management, payroll processing, and asset tracking."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["SOC2"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["ERP_PACK"]
