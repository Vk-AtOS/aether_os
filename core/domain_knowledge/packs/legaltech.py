"""LegalTech domain knowledge pack — attorney-client privilege, IOLTA, ABA Model Rules."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="legaltech",
    display_name="Legal / LegalTech / Law Firm Management",

    entities=[
        EntityTemplate(
            name="Client", table="clients",
            description="Law firm client — conflict check required before matter creation",
            fields=[
                FieldDef("client_id", "string"),
                FieldDef("name", "string", pii=True, encrypted_at_rest=True),
                FieldDef("entity_type", "string"),        # individual | corporation | government
                FieldDef("contact_email", "string", pii=True, encrypted_at_rest=True),
                FieldDef("conflicts_checked", "bool"),
                FieldDef("intake_date", "datetime"),
                FieldDef("status", "string"),             # active | inactive | terminated
            ],
            indexes=["name", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Matter", table="matters",
            description="Legal matter / case — requires conflict check before opening",
            fields=[
                FieldDef("matter_id", "string"),
                FieldDef("client_id", "fk", pii=True),
                FieldDef("matter_type", "string"),        # litigation | transactional | advisory | ip
                FieldDef("title", "string"),
                FieldDef("description", "text", pii=True, encrypted_at_rest=True),
                FieldDef("status", "string"),
                FieldDef("opened_at", "datetime"),
                FieldDef("closed_at", "datetime", required=False),
                FieldDef("billing_partner_id", "fk"),
                FieldDef("responsible_attorney_id", "fk"),
                FieldDef("jurisdiction", "string"),
                FieldDef("practice_area", "string"),
            ],
            indexes=["client_id", "status", "practice_area"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="TimeEntry", table="time_entries",
            description="Billable time record — immutable once billed",
            fields=[
                FieldDef("matter_id", "fk"),
                FieldDef("attorney_id", "fk"),
                FieldDef("date", "datetime"),
                FieldDef("hours", "float"),
                FieldDef("billing_rate_cents", "int"),
                FieldDef("description", "text", pii=True, encrypted_at_rest=True),
                FieldDef("status", "string"),             # draft | submitted | approved | billed
                FieldDef("billable", "bool"),
                FieldDef("task_code", "string"),
            ],
            indexes=["matter_id", "attorney_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="PrivilegeLog", table="privilege_logs",
            description="Attorney-client privilege assertion — excludes document from discovery",
            fields=[
                FieldDef("matter_id", "fk"),
                FieldDef("document_id", "fk"),
                FieldDef("privilege_type", "string"),     # attorney_client | work_product | common_interest
                FieldDef("assertion_basis", "text", encrypted_at_rest=True),
                FieldDef("asserted_by", "fk"),
                FieldDef("asserted_at", "datetime"),
            ],
            indexes=["matter_id", "document_id", "privilege_type"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="CourtFiling", table="court_filings",
            description="Court filing with mandatory deadline tracking",
            fields=[
                FieldDef("matter_id", "fk"),
                FieldDef("filing_type", "string"),        # complaint | motion | brief | order
                FieldDef("court_name", "string"),
                FieldDef("case_number", "string"),
                FieldDef("filed_at", "datetime", required=False),
                FieldDef("due_at", "datetime"),
                FieldDef("status", "string"),             # draft | review | ready | filed | acknowledged | rejected
                FieldDef("document_id", "fk"),
            ],
            indexes=["matter_id", "status", "due_at"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="MatterLifecycle",
            entity="Matter", field="status",
            states=["intake", "conflict_check", "active", "billing_review", "closed", "archived"],
            transitions={
                "intake":           ["conflict_check"],
                "conflict_check":   ["active", "closed"],
                "active":           ["billing_review", "closed"],
                "billing_review":   ["closed"],
                "closed":           ["archived"],
                "archived":         [],
            },
            terminal_states=["archived"],
            description="Matter must clear conflict check before becoming active",
        ),
        WorkflowTemplate(
            name="FilingWorkflow",
            entity="CourtFiling", field="status",
            states=["draft", "review", "ready", "filed", "acknowledged", "rejected"],
            transitions={
                "draft":        ["review"],
                "review":       ["ready", "draft"],
                "ready":        ["filed"],
                "filed":        ["acknowledged", "rejected"],
                "acknowledged": [],
                "rejected":     [],
            },
            terminal_states=["acknowledged", "rejected"],
            description="Court filing review and submission lifecycle",
        ),
    ],

    compliance=[
        ComplianceRule(
            "Attorney-Client Privilege",
            "All privileged communications must be excluded from discovery",
            ["privilege_type", "document_id"],
            "mandatory",
            "Check PrivilegeLog before any document production; never expose privileged docs via API",
        ),
        ComplianceRule(
            "ABA Model Rule 1.6",
            "Client confidentiality — all client data must be encrypted at rest",
            ["Client.name", "Client.contact_email", "Matter.description"],
            "mandatory",
            "AES-256 encryption on all PII fields; access restricted to assigned attorneys only",
        ),
        ComplianceRule(
            "IOLTA",
            "Client trust funds must be segregated — never commingled with operating funds",
            [],
            "mandatory",
            "Trust account ledger must be separate from firm operating account; reconcile monthly",
        ),
        ComplianceRule(
            "GDPR Article 17",
            "Right to erasure — matter records must support anonymization on client request",
            ["Client.name", "Client.contact_email", "Matter.description"],
            "mandatory",
            "Pseudonymisation endpoint required; replace PII with anonymized tokens on request",
        ),
    ],

    api_patterns=[
        "Conflict of interest check before matter creation",
        "Trust accounting endpoints (IOLTA compliance)",
        "Time entry approval workflows",
        "Document privilege assertion API",
        "Court deadline calendar integration",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="MatterOpeningFlow",
            trigger="user_action",
            trigger_entity="Matter",
            trigger_condition="status == 'intake'",
            description="Conflict check, client validation, and matter activation flow.",
            services_required=["ConflictService", "ClientService", "MatterService", "NotificationService"],
            integrations_required=[],
            steps=[
                ProcessStep(
                    name="run_conflict_check",
                    action_type="service_call",
                    service="ConflictService",
                    method="check_conflicts",
                    input_mapping={
                        "client_id": "entity.client_id",
                        "matter_type": "entity.matter_type",
                        "jurisdiction": "entity.jurisdiction",
                    },
                    on_success="validate_client",
                    on_failure="FAIL",
                    timeout_seconds=30,
                    description="Search all existing matters for conflicts — mandatory before activation",
                ),
                ProcessStep(
                    name="validate_client",
                    action_type="service_call",
                    service="ClientService",
                    method="validate_active",
                    input_mapping={"client_id": "entity.client_id"},
                    on_success="activate_matter",
                    on_failure="FAIL",
                    description="Confirm client record is complete and active",
                ),
                ProcessStep(
                    name="activate_matter",
                    action_type="state_transition",
                    service="Matter",
                    method="status",
                    input_mapping={"status": "'active'"},
                    on_success="notify_attorney",
                    on_failure="FAIL",
                    description="Transition matter from conflict_check to active",
                ),
                ProcessStep(
                    name="notify_attorney",
                    action_type="notification",
                    service="NotificationService",
                    method="send_matter_opened",
                    input_mapping={
                        "attorney_id": "entity.responsible_attorney_id",
                        "matter_id": "entity.matter_id",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    description="Notify responsible attorney that matter is now active",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is a law firm management system. Attorney-client privilege is paramount — "
        "all privileged communications must be tagged and protected from unauthorized access. "
        "Trust accounts (IOLTA) are strictly regulated — never mix client funds with operating funds. "
        "Conflict checks must run before any new matter is created. "
        "All time entries must be immutable once billed."
    ),
)
