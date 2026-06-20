"""Healthcare domain knowledge pack — HIPAA, FHIR R4, consent management."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="healthcare",
    display_name="Healthcare / Clinical Systems",

    entities=[
        EntityTemplate(
            name="Patient", table="patients",
            description="FHIR Patient resource — the core identity in clinical systems",
            fields=[
                FieldDef("mrn", "string", pii=True, phi=True, encrypted_at_rest=True),
                FieldDef("given_name", "string", phi=True, encrypted_at_rest=True),
                FieldDef("family_name", "string", phi=True, encrypted_at_rest=True),
                FieldDef("date_of_birth", "datetime", phi=True, encrypted_at_rest=True),
                FieldDef("gender", "string", phi=True),
                FieldDef("phone", "string", phi=True, encrypted_at_rest=True),
                FieldDef("email", "string", phi=True, encrypted_at_rest=True),
                FieldDef("address_line1", "string", phi=True, encrypted_at_rest=True),
                FieldDef("insurance_id", "string", phi=True, encrypted_at_rest=True),
                FieldDef("status", "string"),              # active | inactive | deceased
            ],
            indexes=["mrn", "family_name"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Practitioner", table="practitioners",
            description="FHIR Practitioner — clinician or healthcare provider",
            fields=[
                FieldDef("npi", "string"),                 # National Provider Identifier
                FieldDef("given_name", "string"),
                FieldDef("family_name", "string"),
                FieldDef("specialty", "string"),
                FieldDef("license_number", "string"),
                FieldDef("department_id", "fk"),
                FieldDef("status", "string"),
            ],
            indexes=["npi", "specialty"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Appointment", table="appointments",
            description="Scheduled clinical encounter",
            fields=[
                FieldDef("patient_id", "fk", phi=True),
                FieldDef("practitioner_id", "fk"),
                FieldDef("start_time", "datetime"),
                FieldDef("end_time", "datetime"),
                FieldDef("appointment_type", "string"),    # checkup | follow_up | urgent | telehealth
                FieldDef("status", "string"),
                FieldDef("reason", "text", phi=True, encrypted_at_rest=True),
                FieldDef("notes", "text", phi=True, encrypted_at_rest=True),
            ],
            indexes=["patient_id", "practitioner_id", "start_time", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Encounter", table="encounters",
            description="FHIR Encounter — a clinical visit or interaction",
            fields=[
                FieldDef("patient_id", "fk", phi=True),
                FieldDef("practitioner_id", "fk"),
                FieldDef("appointment_id", "fk"),
                FieldDef("encounter_type", "string"),
                FieldDef("status", "string"),
                FieldDef("started_at", "datetime"),
                FieldDef("ended_at", "datetime"),
                FieldDef("primary_diagnosis_code", "string", phi=True),
                FieldDef("discharge_disposition", "string"),
            ],
            indexes=["patient_id", "status", "started_at"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Observation", table="observations",
            description="FHIR Observation — vital signs, lab results, assessments",
            fields=[
                FieldDef("patient_id", "fk", phi=True),
                FieldDef("encounter_id", "fk"),
                FieldDef("loinc_code", "string"),          # LOINC observation code
                FieldDef("display_name", "string"),
                FieldDef("value_quantity", "float", phi=True),
                FieldDef("value_string", "string", phi=True),
                FieldDef("unit", "string"),
                FieldDef("effective_at", "datetime"),
                FieldDef("status", "string"),              # registered | preliminary | final | amended
            ],
            indexes=["patient_id", "loinc_code", "effective_at"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="ConsentRecord", table="consent_records",
            description="Patient consent for data use, treatment, or sharing",
            fields=[
                FieldDef("patient_id", "fk", phi=True),
                FieldDef("consent_type", "string"),        # treatment | data_sharing | research
                FieldDef("status", "string"),
                FieldDef("granted_at", "datetime"),
                FieldDef("expires_at", "datetime"),
                FieldDef("revoked_at", "datetime"),
                FieldDef("scope", "text"),
            ],
            indexes=["patient_id", "consent_type", "status"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="AppointmentBooking",
            entity="Appointment", field="status",
            states=["requested", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show"],
            transitions={
                "requested":    ["confirmed", "cancelled"],
                "confirmed":    ["checked_in", "cancelled", "no_show"],
                "checked_in":   ["in_progress", "cancelled"],
                "in_progress":  ["completed"],
                "completed":    [],
                "cancelled":    ["requested"],
                "no_show":      [],
            },
            terminal_states=["completed", "no_show"],
            description="Clinical appointment lifecycle",
        ),
        WorkflowTemplate(
            name="ConsentLifecycle",
            entity="ConsentRecord", field="status",
            states=["pending", "granted", "revoked", "expired"],
            transitions={
                "pending": ["granted", "revoked"],
                "granted": ["revoked", "expired"],
                "revoked": [],
                "expired": [],
            },
            terminal_states=["revoked", "expired"],
            description="Patient consent management",
        ),
    ],

    compliance=[
        ComplianceRule("HIPAA", "All PHI must be encrypted at rest and in transit",
                       ["mrn", "given_name", "family_name", "date_of_birth", "phone",
                        "email", "insurance_id", "diagnosis_code", "notes"],
                       "mandatory", "AES-256 at rest, TLS 1.2+ in transit"),
        ComplianceRule("HIPAA", "All PHI access must be logged with user, timestamp, and purpose",
                       [], "mandatory",
                       "Audit log table with every SELECT, INSERT, UPDATE, DELETE on PHI tables"),
        ComplianceRule("HIPAA", "Minimum necessary standard — APIs must not expose more PHI than needed",
                       [], "mandatory",
                       "Field-level access control; never return full record when subset suffices"),
        ComplianceRule("HIPAA", "Patient must have active consent before data is shared",
                       ["patient_id"], "mandatory",
                       "Check ConsentRecord.status == granted before any data-sharing API call"),
        ComplianceRule("GDPR", "Right to access and erasure applies to EU patients",
                       ["email", "phone", "address_line1"], "mandatory",
                       "Pseudonymisation endpoint required; support data export in FHIR format"),
        ComplianceRule("HITECH", "Breach notification within 60 days of discovery",
                       [], "mandatory",
                       "Implement breach detection alerting; store breach_log table"),
    ],

    api_patterns=[
        "GET /patients/{id} — FHIR Patient resource",
        "GET /patients/{id}/encounters — encounter history",
        "GET /patients/{id}/observations?code=LOINC — filtered observations",
        "POST /appointments/book — create appointment with conflict check",
        "PUT /appointments/{id}/status — state machine transition",
        "POST /consent/grant — record patient consent",
        "DELETE /consent/{id} — revoke consent",
        "GET /practitioners/{id}/schedule?date= — availability slots",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="AppointmentBookingFlow",
            trigger="create",
            trigger_entity="Appointment",
            trigger_condition="status == requested",
            description="Full appointment booking: validate patient, check eligibility, assign provider, confirm, notify.",
            integrations_required=["NotificationService", "SchedulingService", "InsuranceService"],
            steps=[
                ProcessStep(
                    name="validate_patient",
                    service_required="PatientService",
                    method="validate",
                    description="Verify patient record exists, is active, and has valid contact info.",
                    input_keys=["patient_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="check_eligibility",
                    service_required="InsuranceService",
                    method="check_eligibility",
                    description="Verify insurance coverage is active for the appointment type.",
                    input_keys=["patient_id", "appointment_type"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="assign_provider",
                    service_required="SchedulingService",
                    method="assign_available_provider",
                    description="Find an available practitioner matching the appointment type and requested time slot.",
                    input_keys=["appointment_type", "start_time", "end_time"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="confirm_appointment",
                    service_required="SchedulingService",
                    method="confirm",
                    description="Lock the time slot and update appointment status to confirmed.",
                    input_keys=["assign_provider", "patient_id", "start_time"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="notify_patient",
                    service_required="NotificationService",
                    method="send_appointment_confirmation",
                    description="Send confirmation email/SMS to patient with appointment details.",
                    input_keys=["patient_id", "confirm_appointment"],
                    on_failure="SKIP",
                ),
            ],
        ),
        BusinessProcessPipeline(
            name="ClaimSubmissionFlow",
            trigger="status_change",
            trigger_entity="Encounter",
            trigger_condition="status == completed",
            description="Insurance claim submission after encounter completion: code, validate, submit, track.",
            integrations_required=["InsuranceService", "NotificationService"],
            steps=[
                ProcessStep(
                    name="extract_diagnosis_codes",
                    service_required="CodingService",
                    method="extract_icd10_codes",
                    description="Extract ICD-10 diagnosis codes and CPT procedure codes from the encounter record.",
                    input_keys=["encounter_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="validate_claim",
                    service_required="InsuranceService",
                    method="validate_claim",
                    description="Validate claim completeness and eligibility before submission.",
                    input_keys=["extract_diagnosis_codes", "patient_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="submit_claim",
                    service_required="InsuranceService",
                    method="submit_claim",
                    description="Submit validated claim to the insurance payer via EDI 837.",
                    input_keys=["validate_claim", "encounter_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="notify_billing",
                    service_required="NotificationService",
                    method="send_claim_submitted",
                    description="Notify the billing department that the claim has been submitted.",
                    input_keys=["submit_claim"],
                    on_failure="SKIP",
                ),
            ],
        ),
    ],

    prompt_injection="""HEALTHCARE DOMAIN RULES (mandatory — HIPAA compliance required):
1. All PHI fields (name, DOB, MRN, diagnosis, insurance_id, phone, email) MUST be encrypted at rest using AES-256.
2. Every database query touching PHI tables MUST write to an audit_log (user_id, action, table, record_id, timestamp).
3. Follow FHIR R4 resource naming: Patient, Practitioner, Encounter, Observation, Appointment, Consent.
4. Never expose PHI in URL path parameters or query strings — use request body or headers.
5. Patient data sharing requires an active ConsentRecord (status == granted, not expired/revoked).
6. Implement minimum-necessary principle: APIs must return only fields required for the use case.
7. Observation values use LOINC codes for interoperability — include loinc_code on every Observation.
8. Appointment scheduling must check practitioner availability and prevent double-booking.
9. All PHI must transit over TLS 1.2 minimum — enforce HTTPS-only.
10. Right-to-erasure: provide a pseudonymisation endpoint that replaces PHI with anonymised tokens.
""",
)
