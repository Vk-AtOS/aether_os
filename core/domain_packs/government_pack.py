"""
Government / Public Sector Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and architecture
notes for generating correct government service management backends and frontends.
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
        name="Officer",
        description=(
            "Government staff member who processes applications. "
            "Role hierarchy: officer → supervisor → admin."
        ),
        typical_fields=[
            "id", "name",
            "badge_number",   # unique — e.g. OFF-001
            "department",
            "role",           # officer / supervisor / admin
            "email",          # unique
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["badge_number", "email"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["badge_number", "email", "role", "is_active"],
    ),
    EntitySpec(
        name="Citizen",
        description=(
            "A registered member of the public who applies for government services. "
            "national_id is sensitive — must never appear in logs."
        ),
        typical_fields=[
            "id", "full_name",
            "national_id",  # unique — GOV-NID-001 format; NEVER logged
            "dob",          # date of birth
            "email",
            "phone",
            "address",
            "verified",     # Boolean — identity verified by an officer
            "created_at", "updated_at",
        ],
        unique_fields=["national_id", "email"],
        fk_relationships=[],
        compliance_fields=["national_id"],  # PII — must be protected
        indexes=["national_id", "email", "verified"],
    ),
    EntitySpec(
        name="Service",
        description=(
            "A government service citizens can apply for (e.g. passport, driving licence). "
            "SLA days define the maximum processing window."
        ),
        typical_fields=[
            "id", "name",         # unique
            "description",
            "category",           # identity / transport / property / business / legal
            "sla_days",           # Integer — government SLA for processing
            "fee_amount",         # Numeric(12,2) — zero for free services
            "active",             # Boolean
            "created_at", "updated_at",
        ],
        unique_fields=["name"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["name", "category", "active"],
    ),
    EntitySpec(
        name="Application",
        description=(
            "A citizen's request for a specific government service. "
            "reference_number is auto-generated; citizens cannot set it."
        ),
        typical_fields=[
            "id",
            "citizen_id",          # FK → Citizen
            "service_id",          # FK → Service
            "reference_number",    # unique — auto-generated REF-{YYYY}-{i:06d}; read-only
            "status",              # submitted / under_review / approved / rejected
            "submitted_at",
            "processed_at",        # nullable — set when approved or rejected
            "created_at", "updated_at",
        ],
        unique_fields=["reference_number"],
        fk_relationships=[
            "citizen_id -> Citizen.id",
            "service_id -> Service.id",
        ],
        compliance_fields=[],
        indexes=["reference_number", "citizen_id", "service_id", "status"],
    ),
    EntitySpec(
        name="Document",
        description=(
            "A supporting document uploaded with an Application. "
            "Verification is done by an Officer."
        ),
        typical_fields=[
            "id",
            "application_id",  # FK → Application
            "doc_type",        # identity_proof / address_proof / income_proof / photograph / other
            "file_path",       # unique
            "verified",        # Boolean
            "verified_by_id",  # nullable FK → Officer
            "created_at", "updated_at",
        ],
        unique_fields=["file_path"],
        fk_relationships=[
            "application_id -> Application.id",
            "verified_by_id -> Officer.id",
        ],
        compliance_fields=[],
        indexes=["application_id", "doc_type", "verified"],
    ),
    EntitySpec(
        name="AuditLog",
        description=(
            "Immutable audit trail for all data access and mutations. "
            "Every READ of citizen data must create an AuditLog entry. "
            "national_id must NEVER appear in this table."
        ),
        typical_fields=[
            "id",
            "entity_type",   # e.g. Citizen, Application, Document
            "entity_id",     # Integer — the PK of the affected record
            "action",        # create / read / update / delete
            "officer_id",    # nullable FK → Officer (None for system actions)
            "ip_address",    # String(45) — IPv4 or IPv6
            "timestamp",     # DateTime UTC — always UTC; no updated_at (append-only)
        ],
        unique_fields=[],
        fk_relationships=["officer_id -> Officer.id"],
        compliance_fields=["officer_id", "ip_address"],
        indexes=["entity_type", "entity_id", "action", "officer_id", "timestamp"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="sendgrid",
        purpose=(
            "Application status notifications to citizens: "
            "submission confirmation, under-review alert, approval/rejection notice"
        ),
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_application_submitted",
            "send_application_approved",
            "send_application_rejected",
            "send_document_verification_required",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # Accessibility
    "All generated UI MUST comply with WCAG 2.1 AA — use semantic HTML, aria-label on all interactive elements, and sufficient colour contrast (4.5:1 minimum).",
    # Audit requirements
    "Every READ of citizen data MUST create an AuditLog entry with entity_type, entity_id, action='read', officer_id, ip_address, and UTC timestamp.",
    "AuditLog records are IMMUTABLE — no UPDATE or DELETE endpoints; the table is append-only.",
    # PII protection
    "Citizen.national_id MUST NEVER appear in any log line, error message, or audit record — use Citizen.id (integer PK) in all references.",
    "Citizen.national_id MUST NOT be returned in list endpoints — only in the individual citizen detail endpoint, gated to authenticated officers.",
    # Reference number
    "Application.reference_number MUST be auto-generated server-side using the pattern REF-{YYYY}-{i:06d} — the API MUST reject any client-supplied reference_number.",
    "Application.reference_number MUST be unique and indexed.",
    # Status enum
    "Application.status MUST use an Enum: submitted / under_review / approved / rejected — never a free-form string.",
    "Application.processed_at MUST be set (UTC) when status transitions to 'approved' or 'rejected' — enforce in the service layer.",
    # Timestamps
    "All timestamps MUST be stored in UTC (DateTime(timezone=True)) — reject timezone-naive inputs at the Pydantic validation layer.",
    # Payment
    "Government fees are handled separately — do NOT integrate Stripe or any third-party payment gateway in this domain pack.",
    # Officer roles
    "Officer.role MUST use an Enum: officer / supervisor / admin — status changes to Application require supervisor or admin role.",
    # Document verification
    "Document.verified_by_id MUST reference an Officer — citizens cannot self-verify their own documents.",
    # SLA tracking
    "Implement SLA breach detection: if Application.submitted_at + Service.sla_days < now() and status not in ('approved', 'rejected'), flag as overdue.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    # 20 citizens with unique national IDs
    "national_id": "GOV-NID-{i:03d}",
    "full_name": "Citizen {i} Surname",
    "email_citizen": "citizen{i:03d}@example.gov",
    "phone": "+1555{i:07d}",
    "address": "{i} Government Street, Capital City",
    # 5 services
    "service_names": "Passport Application|Driving Licence Renewal|Land Permit|Business Registration|Birth Certificate",
    "category": "identity|transport|property|business|legal",
    "sla_days": "30|14|45|21|10",
    "fee_amount": "50.00|25.00|100.00|75.00|15.00",
    # 20 applications
    "reference_number": "REF-2026-{i:06d}",
    "status": "submitted|under_review|approved|rejected",
    # Officers
    "badge_number": "OFF-{i:03d}",
    "role_officer": "officer|supervisor|admin",
    "email_officer": "officer{i:03d}@gov.example.com",
    # Documents
    "doc_type": "identity_proof|address_proof|income_proof|photograph|other",
    "file_path": "/uploads/doc-{i:04d}.pdf",
    # Seed counts
    "seed_counts": "citizens:20, services:5, applications:20, officers:5, documents:20",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Audit trail: inject an audit_log service dependency into every endpoint — call audit_log.record(entity_type, entity_id, action, request) on every read and write.",
    "PII masking: implement a Citizen serializer that masks national_id in list responses — return only the last 3 digits (e.g. ***-001) in list views.",
    "Reference number generation: use a DB sequence (PostgreSQL SERIAL or a dedicated counter table) to generate REF-{YYYY}-{i:06d} atomically — never generate in application code with random().",
    "Role-based access: implement get_current_officer_with_role dependency — supervisor or admin required for Application status updates; officer role sufficient for document verification.",
    "WCAG compliance: generate frontend with semantic HTML5 elements (<nav>, <main>, <section>, <form>), skip-navigation links, and keyboard-accessible modals.",
    "SLA monitoring: implement a background task (APScheduler or FastAPI lifespan) that runs hourly, queries overdue applications, and sends alert emails to supervisors.",
    "Soft delete: never hard-delete citizen or application records — add deleted_at (nullable DateTime) and filter in all queries.",
    "Immutable audit log: use a PostgreSQL trigger or application-layer guard to prevent UPDATE/DELETE on the audit_logs table.",
    "UTC enforcement: use server_default=func.now() with timezone=True on all timestamp columns — never use datetime.now() without tz info.",
    "Document storage: store only file_path references — actual files go to S3-compatible storage; never store binary blobs in Postgres.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

GOVERNMENT_PACK = DomainPack(
    domain="government",
    display_name="Government / Public Sector",
    description=(
        "Government service management platform for citizen applications, "
        "document verification, officer workflows, and immutable audit trails. "
        "WCAG 2.1 AA compliant UI required."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["GDPR", "WCAG-2.1-AA"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["GOVERNMENT_PACK"]
