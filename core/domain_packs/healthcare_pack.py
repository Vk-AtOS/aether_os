"""
Healthcare Domain Pack for AetherOS.

Carries canonical entity graph, HIPAA constraints, integrations, and seed
patterns for generating correct healthcare/EHR backends and frontends.
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
        description="Hospital or clinic department; referenced by Doctors and Appointments.",
        typical_fields=[
            "id", "name", "code", "description", "head_doctor_id",
            "phone_extension", "location", "is_active", "created_at", "updated_at",
        ],
        unique_fields=["code"],
        fk_relationships=[],  # head_doctor_id added after Doctor entity exists
        compliance_fields=[],
        indexes=["code", "is_active"],
    ),
    EntitySpec(
        name="Doctor",
        description="Licensed medical practitioner attached to a Department.",
        typical_fields=[
            "id", "employee_id", "first_name", "last_name", "email",
            "license_number", "specialty", "department_id",
            "is_active", "created_at", "updated_at",
            # HIPAA: no SSN stored in plaintext
        ],
        unique_fields=["employee_id", "email", "license_number"],
        fk_relationships=["department_id -> Department.id"],
        compliance_fields=["created_at", "updated_at"],  # audit trail
        indexes=["employee_id", "email", "license_number", "department_id"],
    ),
    EntitySpec(
        name="Patient",
        description=(
            "Registered patient; all PHI fields are marked for field-level "
            "encryption. No SSN stored in plaintext."
        ),
        typical_fields=[
            "id", "mrn",  # Medical Record Number: MRN-{i:06d}
            "first_name", "last_name", "email", "phone",
            "date_of_birth",  # HIPAA: encrypt / mask in responses
            "gender", "blood_type",
            "emergency_contact_name", "emergency_contact_phone",
            "is_active", "is_deleted",  # soft-delete for HIPAA retention
            "created_at", "updated_at", "created_by", "updated_by",
        ],
        unique_fields=["mrn", "email"],
        fk_relationships=[],
        compliance_fields=[
            "date_of_birth",   # HIPAA PHI — encrypt, mask in API responses
            "created_by", "updated_by",  # HIPAA audit columns
        ],
        indexes=["mrn", "email", "is_active"],
    ),
    EntitySpec(
        name="Appointment",
        description=(
            "Scheduled visit between a Patient and a Doctor. "
            "Status is an Enum to prevent free-form strings."
        ),
        typical_fields=[
            "id", "reference_number",  # APT-{YYYY}-{i:06d}
            "patient_id", "doctor_id", "department_id",
            "appointment_type",  # checkup / follow_up / emergency / surgery / consultation
            "status",  # scheduled / confirmed / in_progress / completed / cancelled / no_show
            "scheduled_at", "duration_minutes",
            "notes",  # HIPAA: PHI, never log
            "room_number",
            "created_at", "updated_at", "created_by", "updated_by",
        ],
        unique_fields=["reference_number"],
        fk_relationships=[
            "patient_id -> Patient.id",
            "doctor_id -> Doctor.id",
            "department_id -> Department.id",
        ],
        compliance_fields=["notes", "created_by", "updated_by"],  # PHI audit
        indexes=["reference_number", "patient_id", "doctor_id", "status", "scheduled_at"],
    ),
    EntitySpec(
        name="MedicalRecord",
        description=(
            "Clinical encounter record attached to a Patient and Appointment. "
            "Contains PHI — all fields encrypted at rest, soft-delete only."
        ),
        typical_fields=[
            "id", "patient_id", "doctor_id", "appointment_id",
            "diagnosis",    # HIPAA PHI — encrypt
            "icd_code",     # International Classification of Diseases code
            "symptoms", "treatment_plan",
            "lab_results_json",  # structured results stored as JSON
            "file_attachments_json",  # storage_path references only — no BLOBs
            "is_deleted", "deleted_at",  # soft-delete, HIPAA 6-year retention
            "created_at", "updated_at", "created_by", "updated_by",
        ],
        unique_fields=[],
        fk_relationships=[
            "patient_id -> Patient.id",
            "doctor_id -> Doctor.id",
            "appointment_id -> Appointment.id",
        ],
        compliance_fields=[
            "diagnosis", "symptoms", "treatment_plan",  # HIPAA PHI
            "created_by", "updated_by",  # audit columns
        ],
        indexes=["patient_id", "doctor_id", "appointment_id", "icd_code"],
    ),
    EntitySpec(
        name="Prescription",
        description=(
            "Medication prescribed to a Patient by a Doctor. "
            "PHI — encrypted at rest, immutable once dispensed."
        ),
        typical_fields=[
            "id", "reference_number",  # RX-{YYYY}-{i:06d}
            "patient_id", "doctor_id",
            "medication_name", "dosage", "frequency", "duration_days",
            "instructions",   # HIPAA PHI
            "status",  # active / dispensed / cancelled / expired
            "dispensed_at", "expires_at",
            "is_deleted",
            "created_at", "updated_at", "created_by", "updated_by",
        ],
        unique_fields=["reference_number"],
        fk_relationships=[
            "patient_id -> Patient.id",
            "doctor_id -> Doctor.id",
        ],
        compliance_fields=[
            "instructions",   # HIPAA PHI
            "created_by", "updated_by",
        ],
        indexes=["reference_number", "patient_id", "doctor_id", "status"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="sendgrid",
        purpose="Appointment reminders, prescription-ready notifications, password reset",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_appointment_reminder",
            "send_prescription_ready",
            "send_password_reset",
            "send_test_results_notification",
        ],
    ),
    IntegrationSpec(
        name="twilio",
        purpose="SMS appointment reminders and urgent patient notifications",
        env_vars=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        typical_methods=["client.messages.create"],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # HIPAA PHI protection
    "NEVER store SSN in plaintext — if required, store an encrypted_ssn (bytes) field with comment '# HIPAA: AES-256 encrypted'.",
    "date_of_birth MUST NOT appear in API response bodies — return calculated age (int) instead, or mask as 'XXXX-XX-XX'.",
    "Never log PHI fields (patient name, email, DOB, diagnosis, prescription details) — add '# HIPAA: never log this field' comment above each PHI column definition.",
    # HIPAA audit log
    "Every endpoint that reads patient data MUST write an AuditLog record: (patient_id, action, accessor_user_id, accessor_role, ip_address, timestamp).",
    "Bulk export of patient data requires role='superadmin' AND env var HIPAA_EXPORT_APPROVED=true — reject otherwise with HTTP 403.",
    # RBAC
    "Patient PHI endpoints must gate on role: only 'doctor', 'nurse', 'admin' roles may read PHI — add role check after get_current_user.",
    "Appointment notes and MedicalRecord fields are accessible only to the assigned doctor and admin — not to the patient themselves via API.",
    # Data integrity
    "Patient records use soft-delete only (is_deleted=True, deleted_at=DateTime) — NEVER hard-delete, HIPAA requires 6-year retention.",
    "Appointment status MUST use an Enum: scheduled / confirmed / in_progress / completed / cancelled / no_show.",
    "Medical Record Numbers MUST follow format MRN-{i:06d} and be unique and indexed.",
    "Prescription reference numbers MUST follow format RX-{YYYY}-{i:06d} and be unique.",
    "File/document attachments MUST store a storage_path (str) reference only — never store binary BLOBs in the database.",
    "All ORM models MUST include created_by and updated_by string columns (default='system') for HIPAA audit trails.",
    "Authentication attempts (success and failure) MUST be logged with user_id, IP, outcome, and timestamp.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "mrn": "MRN-{i:06d}",
    "email": "patient_{i}@example.com",
    "phone": "+1555{i:07d}",
    "date_of_birth": "197{i % 10}-0{(i % 9) + 1}-{(i % 28) + 1:02d}",
    "reference_number_appointment": "APT-2026-{i:06d}",
    "reference_number_prescription": "RX-2026-{i:06d}",
    "appointment_type": "checkup|follow_up|emergency|surgery|consultation",
    "status_appointment": "scheduled|confirmed|completed|cancelled|no_show",
    "status_prescription": "active|dispensed|cancelled|expired",
    "icd_code": "J{i:02d}.{i % 9}",
    "employee_id": "EMP-{i:05d}",
    "license_number": "LIC-{i:08d}",
    "file_path": "/files/medical-record-{i:03d}.pdf",
    "specialty": "Cardiology|Dermatology|Neurology|Orthopedics|Pediatrics|Radiology|Surgery|General Practice",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "HIPAA compliance: implement field-level encryption for PHI using a symmetric key stored in env vars (FIELD_ENCRYPTION_KEY).",
    "Audit log: create a separate AuditLog table (id, entity_type, entity_id, action, accessor_id, accessor_role, ip_address, timestamp) and write to it on every PHI read/write.",
    "Soft delete only: add is_deleted (Boolean, default=False) and deleted_at (DateTime, nullable=True) to all patient-related models.",
    "Role-based access: implement RBAC with roles doctor/nurse/admin/receptionist — inject role check in a reusable FastAPI dependency.",
    "Date-of-birth masking: middleware or Pydantic validator must strip or replace dob fields before returning responses.",
    "Appointment reminders: use a background task (FastAPI BackgroundTasks or Celery) to send SendGrid/Twilio reminders 24h and 1h before scheduled_at.",
    "MFA: enforce TOTP-based MFA for all roles that can access PHI — add mfa_secret and mfa_enabled columns to User model.",
    "No bulk export without approval: check HIPAA_EXPORT_APPROVED env var at import time and cache the result — do not re-read per request.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

HEALTHCARE_PACK = DomainPack(
    domain="healthcare",
    display_name="Healthcare / EHR",
    description=(
        "Electronic Health Record (EHR) platform supporting patient management, "
        "appointments, prescriptions, medical records, and HIPAA-compliant audit trails."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["HIPAA"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["HEALTHCARE_PACK"]
