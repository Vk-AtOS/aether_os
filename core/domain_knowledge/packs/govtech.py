"""GovTech domain knowledge pack — FedRAMP, FISMA, NIST 800-53, Section 508, Privacy Act."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="govtech",
    display_name="Government / GovTech / Public Sector",

    entities=[
        EntityTemplate(
            name="CitizenRecord", table="citizen_records",
            description="Citizen identity record — all PII encrypted at rest, Privacy Act applies",
            fields=[
                FieldDef("citizen_id", "string"),
                FieldDef("full_name", "string", pii=True, encrypted_at_rest=True),
                FieldDef("date_of_birth", "datetime", pii=True, encrypted_at_rest=True),
                FieldDef("national_id", "string", pii=True, encrypted_at_rest=True, never_store=False),
                FieldDef("address", "text", pii=True, encrypted_at_rest=True),
                FieldDef("email", "string", pii=True, encrypted_at_rest=True),
                FieldDef("status", "string"),             # active | inactive | suspended
            ],
            indexes=["national_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="ServiceRequest", table="service_requests",
            description="Citizen-initiated government service request",
            fields=[
                FieldDef("request_id", "string"),
                FieldDef("citizen_id", "fk", pii=True),
                FieldDef("service_type", "string"),
                FieldDef("description", "text", pii=True, encrypted_at_rest=True),
                FieldDef("status", "string"),             # submitted | triaged | assigned | in_progress | pending_citizen | resolved | rejected | escalated
                FieldDef("priority", "string"),           # low | normal | high | urgent
                FieldDef("assigned_to", "fk", required=False),
                FieldDef("submitted_at", "datetime"),
                FieldDef("due_at", "datetime", required=False),
                FieldDef("resolved_at", "datetime", required=False),
                FieldDef("resolution", "text", required=False),
            ],
            indexes=["status", "service_type", "assigned_to"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="AuditEvent", table="audit_events",
            description="Append-only audit log — no updates or deletes ever; FISMA required",
            fields=[
                FieldDef("entity_type", "string"),
                FieldDef("entity_id", "string"),
                FieldDef("action", "string"),             # create | read | update | delete
                FieldDef("actor_id", "fk"),
                FieldDef("actor_role", "string"),
                FieldDef("timestamp", "datetime"),
                FieldDef("ip_address", "string"),
                FieldDef("change_summary", "text"),
                FieldDef("session_id", "string"),
            ],
            indexes=["entity_type", "entity_id", "timestamp", "actor_id"],
            audit_trail=False,  # self-referential — is itself the audit log
        ),
        EntityTemplate(
            name="Authorization", table="authorizations",
            description="Authority to Operate (ATO) or delegated authorization record",
            fields=[
                FieldDef("entity_type", "string"),
                FieldDef("authorized_by", "fk"),
                FieldDef("authorized_at", "datetime"),
                FieldDef("authorization_level", "string"),
                FieldDef("expiry_at", "datetime"),
                FieldDef("status", "string"),             # initiated | security_assessment | risk_review | approved | denied | withdrawn
                FieldDef("justification", "text", encrypted_at_rest=True),
            ],
            indexes=["entity_type", "status", "expiry_at"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="PublicDocument", table="public_documents",
            description="Government document with classification and Section 508 compliance tracking",
            fields=[
                FieldDef("document_id", "string"),
                FieldDef("title", "string"),
                FieldDef("document_type", "string"),
                FieldDef("classification", "string"),     # public | internal | restricted | classified
                FieldDef("version", "string"),
                FieldDef("published_at", "datetime", required=False),
                FieldDef("effective_date", "datetime", required=False),
                FieldDef("expiry_date", "datetime", required=False),
                FieldDef("status", "string"),             # draft | review | published | archived
                FieldDef("section_508_compliant", "bool"),
            ],
            indexes=["classification", "status", "document_type"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="ServiceRequestFlow",
            entity="ServiceRequest", field="status",
            states=[
                "submitted", "triaged", "assigned", "in_progress",
                "pending_citizen", "resolved", "rejected", "escalated",
            ],
            transitions={
                "submitted":       ["triaged"],
                "triaged":         ["assigned", "rejected"],
                "assigned":        ["in_progress"],
                "in_progress":     ["pending_citizen", "resolved", "escalated"],
                "pending_citizen": ["in_progress", "resolved"],
                "resolved":        [],
                "rejected":        [],
                "escalated":       ["in_progress", "resolved"],
            },
            terminal_states=["resolved", "rejected"],
            description="Citizen service request from submission to resolution",
        ),
        WorkflowTemplate(
            name="AuthorizationFlow",
            entity="Authorization", field="status",
            states=[
                "initiated", "security_assessment", "risk_review", "approved", "denied", "withdrawn",
            ],
            transitions={
                "initiated":          ["security_assessment"],
                "security_assessment": ["risk_review"],
                "risk_review":        ["approved", "denied"],
                "approved":           ["withdrawn"],
                "denied":             [],
                "withdrawn":          [],
            },
            terminal_states=["approved", "denied", "withdrawn"],
            description="ATO security assessment and risk review pipeline",
        ),
    ],

    compliance=[
        ComplianceRule(
            "FedRAMP Moderate",
            "Cloud services must meet FedRAMP Moderate baseline (325 controls)",
            [],
            "mandatory",
            "AES-256 at rest, TLS 1.2+ in transit, MFA required for all access; annual pen test",
        ),
        ComplianceRule(
            "FISMA",
            "Continuous monitoring required — all actions logged in AuditEvent",
            ["AuditEvent.timestamp", "AuditEvent.actor_id"],
            "mandatory",
            "Every mutation must write to AuditEvent before committing; SIEM integration required",
        ),
        ComplianceRule(
            "NIST 800-53 AC-2",
            "User accounts must be reviewed quarterly",
            ["CitizenRecord.status"],
            "mandatory",
            "Scheduled job to flag accounts inactive > 90 days for review; disable after 180 days",
        ),
        ComplianceRule(
            "Section 508",
            "All UI components must meet WCAG 2.1 AA for public-facing interfaces",
            [],
            "mandatory",
            "Inject Section 508 requirements into P07c accessibility testing phase",
        ),
        ComplianceRule(
            "Privacy Act of 1974",
            "Federal agencies cannot maintain secret records on citizens — all data collection must be disclosed",
            ["CitizenRecord.full_name", "CitizenRecord.national_id", "ServiceRequest.description"],
            "mandatory",
            "System of Records Notice (SORN) must be published; citizens have right to access their records",
        ),
    ],

    api_patterns=[
        "ATO (Authority to Operate) workflow endpoints",
        "FOIA (Freedom of Information) request handling",
        "Multi-factor authentication enforcement",
        "Continuous monitoring dashboard (SIEM integration)",
        "Citizen notification via gov.notify or USPS API",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="ServiceRequestResolutionFlow",
            trigger="state_transition",
            trigger_entity="ServiceRequest",
            trigger_condition="status == 'submitted'",
            description="Triage, assign, process, and resolve citizen service requests with full audit trail.",
            services_required=[
                "TriageService", "AssignmentService", "AuditService",
                "NotificationService", "ServiceRequestService",
            ],
            integrations_required=[],
            steps=[
                ProcessStep(
                    name="log_submission",
                    action_type="service_call",
                    service="AuditService",
                    method="log_event",
                    input_mapping={
                        "entity_type": "'ServiceRequest'",
                        "entity_id": "entity.request_id",
                        "action": "'create'",
                        "actor_id": "entity.citizen_id",
                    },
                    on_success="triage_request",
                    on_failure="FAIL",
                    timeout_seconds=5,
                    description="Write AuditEvent before any other action — FISMA mandatory",
                ),
                ProcessStep(
                    name="triage_request",
                    action_type="service_call",
                    service="TriageService",
                    method="classify_and_prioritize",
                    input_mapping={
                        "service_type": "entity.service_type",
                        "description": "entity.description",
                    },
                    on_success="assign_to_agent",
                    on_failure="FAIL",
                    description="Classify request type and set priority level",
                ),
                ProcessStep(
                    name="assign_to_agent",
                    action_type="service_call",
                    service="AssignmentService",
                    method="find_and_assign",
                    input_mapping={
                        "service_type": "entity.service_type",
                        "priority": "entity.priority",
                        "request_id": "entity.request_id",
                    },
                    on_success="notify_citizen",
                    on_failure="FAIL",
                    description="Route request to available agent based on service type",
                ),
                ProcessStep(
                    name="notify_citizen",
                    action_type="notification",
                    service="NotificationService",
                    method="send_request_received",
                    input_mapping={
                        "citizen_id": "entity.citizen_id",
                        "request_id": "entity.request_id",
                        "due_at": "entity.due_at",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    description="Notify citizen their request was received and assigned",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is a government system subject to FedRAMP, FISMA, and the Privacy Act. "
        "All actions must be logged in the AuditEvent table — no mutation without a corresponding audit entry. "
        "MFA is mandatory for all user sessions. "
        "Data classification must be enforced — citizens can only see their own records. "
        "Section 508 accessibility is legally required for all public-facing interfaces."
    ),
)
