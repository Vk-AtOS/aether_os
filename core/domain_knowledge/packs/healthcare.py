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

    pipelines=[
        BusinessProcessPipeline(
            name="AppointmentBookingFlow",
            trigger="state_transition",
            trigger_entity="Appointment",
            trigger_condition="status transitions to 'requested'",
            description="End-to-end flow from appointment request through insurance eligibility, "
                        "provider assignment, confirmation, and patient notification.",
            services_required=[
                "PatientService", "InsuranceService", "SchedulingService",
                "NotificationService", "SchedulerService",
            ],
            integrations_required=["sendgrid", "twilio"],
            steps=[
                ProcessStep(
                    name="validate_patient",
                    action_type="service_call",
                    service="PatientService",
                    method="validate",
                    input_mapping={"patient_id": "entity.patient_id"},
                    on_success="check_insurance_eligibility",
                    on_failure="FAIL",
                    description="Confirm patient record is active and complete",
                ),
                ProcessStep(
                    name="check_insurance_eligibility",
                    action_type="service_call",
                    service="InsuranceService",
                    method="check_eligibility",
                    input_mapping={
                        "patient_id": "entity.patient_id",
                        "appointment_type": "entity.appointment_type",
                    },
                    on_success="assign_provider",
                    on_failure="FAIL",
                    description="Verify insurance covers this appointment type",
                ),
                ProcessStep(
                    name="assign_provider",
                    action_type="service_call",
                    service="SchedulingService",
                    method="find_available_provider",
                    input_mapping={
                        "appointment_type": "entity.appointment_type",
                        "start_time": "entity.start_time",
                    },
                    on_success="confirm_appointment",
                    on_failure="FAIL",
                    description="Find a practitioner with an open slot — prevents double-booking",
                ),
                ProcessStep(
                    name="confirm_appointment",
                    action_type="state_transition",
                    service="Appointment",
                    method="status",
                    input_mapping={"status": "'confirmed'"},
                    on_success="send_confirmation_email",
                    on_failure="FAIL",
                    compensation="revert_to_requested",
                    description="Transition appointment status to confirmed",
                ),
                ProcessStep(
                    name="send_confirmation_email",
                    action_type="notification",
                    service="NotificationService",
                    method="send_email",
                    input_mapping={
                        "patient_id": "entity.patient_id",
                        "template": "'appointment_confirmed'",
                    },
                    on_success="schedule_reminder",
                    on_failure="SKIP",
                    description="Email patient confirmation — non-fatal if sendgrid is unavailable",
                ),
                ProcessStep(
                    name="schedule_reminder",
                    action_type="schedule",
                    service="SchedulerService",
                    method="schedule_24h_reminder",
                    input_mapping={
                        "appointment_id": "entity.id",
                        "patient_id": "entity.patient_id",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    description="Queue a 24-hour SMS/email reminder via Twilio",
                ),
            ],
        ),
        BusinessProcessPipeline(
            name="ClaimSubmissionFlow",
            trigger="state_transition",
            trigger_entity="Encounter",
            trigger_condition="status transitions to 'completed'",
            description="Automated billing flow triggered when a clinical encounter closes: "
                        "creates claim, calculates charges, submits to clearinghouse, "
                        "and notifies the patient.",
            services_required=["BillingService", "InsuranceService", "NotificationService"],
            integrations_required=["clearinghouse_api", "sendgrid"],
            steps=[
                ProcessStep(
                    name="create_billing_record",
                    action_type="service_call",
                    service="BillingService",
                    method="create_claim",
                    input_mapping={"encounter_id": "entity.id", "patient_id": "entity.patient_id"},
                    on_success="calculate_charges",
                    on_failure="FAIL",
                    description="Create a Claim record linked to the completed encounter",
                ),
                ProcessStep(
                    name="calculate_charges",
                    action_type="service_call",
                    service="BillingService",
                    method="calculate_charges",
                    input_mapping={
                        "claim_id": "steps.create_billing_record.claim_id",
                        "diagnosis_code": "entity.primary_diagnosis_code",
                    },
                    on_success="submit_to_insurance",
                    on_failure="FAIL",
                    description="Apply CPT/ICD-10 charge codes and fee schedules",
                ),
                ProcessStep(
                    name="submit_to_insurance",
                    action_type="external_api",
                    service="InsuranceService",
                    method="submit_claim",
                    input_mapping={"claim_id": "steps.create_billing_record.claim_id"},
                    on_success="record_claim_status",
                    on_failure="FAIL",
                    retry_count=5,
                    timeout_seconds=60,
                    description="POST X12 837 claim to clearinghouse API",
                ),
                ProcessStep(
                    name="record_claim_status",
                    action_type="state_transition",
                    service="Claim",
                    method="status",
                    input_mapping={"status": "'submitted'"},
                    on_success="notify_patient",
                    on_failure="FAIL",
                    description="Mark the Claim record as submitted",
                ),
                ProcessStep(
                    name="notify_patient",
                    action_type="notification",
                    service="NotificationService",
                    method="send_claim_receipt",
                    input_mapping={
                        "patient_id": "entity.patient_id",
                        "claim_id": "steps.create_billing_record.claim_id",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    description="Email patient an EOB-style receipt — non-fatal",
                ),
            ],
        ),
    ],
)
