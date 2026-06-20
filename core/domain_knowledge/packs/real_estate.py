"""Real Estate / PropTech domain knowledge pack — Fair Housing, RESPA, state disclosure laws."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="real_estate",
    display_name="Real Estate / Property Management / PropTech",

    entities=[
        EntityTemplate(
            name="Property", table="properties",
            description="Physical property record — core asset in the platform",
            fields=[
                FieldDef("property_id", "string"),
                FieldDef("address_line1", "string", pii=True, encrypted_at_rest=True),
                FieldDef("city", "string"),
                FieldDef("state", "string"),
                FieldDef("zip", "string"),
                FieldDef("country", "string"),
                FieldDef("property_type", "string"),      # residential | commercial | industrial
                FieldDef("bedrooms", "int", required=False),
                FieldDef("bathrooms", "float", required=False),
                FieldDef("square_feet", "float"),
                FieldDef("lot_size_sqft", "float", required=False),
                FieldDef("year_built", "int", required=False),
                FieldDef("status", "string"),             # available | under_contract | sold | off_market
                FieldDef("listing_price_cents", "int"),
                FieldDef("owner_id", "fk"),
            ],
            indexes=["city", "state", "status", "property_type"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Listing", table="listings",
            description="MLS listing — links property to agent and tracks listing lifecycle",
            fields=[
                FieldDef("property_id", "fk"),
                FieldDef("agent_id", "fk"),
                FieldDef("mls_number", "string"),
                FieldDef("list_price_cents", "int"),
                FieldDef("list_date", "datetime"),
                FieldDef("expiry_date", "datetime"),
                FieldDef("status", "string"),             # active | pending | sold | expired | withdrawn
                FieldDef("listing_type", "string"),       # exclusive_right | exclusive_agency | open
            ],
            indexes=["mls_number", "status", "property_id"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Transaction", table="real_estate_transactions",
            description="Property sale transaction — all party PII encrypted at rest",
            fields=[
                FieldDef("property_id", "fk"),
                FieldDef("buyer_id", "fk", pii=True, encrypted_at_rest=True),
                FieldDef("seller_id", "fk", pii=True, encrypted_at_rest=True),
                FieldDef("buyer_agent_id", "fk"),
                FieldDef("seller_agent_id", "fk"),
                FieldDef("sale_price_cents", "int"),
                FieldDef("earnest_money_cents", "int"),
                FieldDef("closing_date", "datetime", required=False),
                FieldDef("status", "string"),
                FieldDef("escrow_company", "string"),
            ],
            indexes=["property_id", "status", "closing_date"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Inspection", table="inspections",
            description="Property inspection tied to a transaction contingency period",
            fields=[
                FieldDef("property_id", "fk"),
                FieldDef("transaction_id", "fk"),
                FieldDef("inspector_id", "fk"),
                FieldDef("inspection_type", "string"),    # general | pest | structural | environmental
                FieldDef("scheduled_at", "datetime"),
                FieldDef("completed_at", "datetime", required=False),
                FieldDef("status", "string"),             # scheduled | in_progress | completed | cancelled
                FieldDef("findings", "text", required=False),
                FieldDef("contingency_deadline", "datetime"),
            ],
            indexes=["property_id", "transaction_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Lease", table="leases",
            description="Tenant lease agreement — tenant PII encrypted at rest",
            fields=[
                FieldDef("property_id", "fk"),
                FieldDef("tenant_id", "fk", pii=True, encrypted_at_rest=True),
                FieldDef("start_date", "datetime"),
                FieldDef("end_date", "datetime"),
                FieldDef("monthly_rent_cents", "int"),
                FieldDef("security_deposit_cents", "int"),
                FieldDef("status", "string"),             # active | expired | terminated | pending
                FieldDef("auto_renewal", "bool"),
            ],
            indexes=["property_id", "tenant_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="TransactionFlow",
            entity="Transaction", field="status",
            states=[
                "offer_submitted", "under_contract", "inspection_period",
                "appraisal", "financing", "clear_to_close", "closed", "cancelled",
            ],
            transitions={
                "offer_submitted":   ["under_contract", "cancelled"],
                "under_contract":    ["inspection_period", "cancelled"],
                "inspection_period": ["appraisal", "cancelled"],
                "appraisal":         ["financing", "cancelled"],
                "financing":         ["clear_to_close", "cancelled"],
                "clear_to_close":    ["closed"],
                "closed":            [],
                "cancelled":         [],
            },
            terminal_states=["closed", "cancelled"],
            description="Property sale transaction lifecycle with contingency periods",
        ),
        WorkflowTemplate(
            name="LeaseRenewal",
            entity="Lease", field="status",
            states=["pending", "sent", "signed", "declined", "expired"],
            transitions={
                "pending":  ["sent"],
                "sent":     ["signed", "declined", "expired"],
                "signed":   [],
                "declined": [],
                "expired":  [],
            },
            terminal_states=["signed", "declined", "expired"],
            description="Lease renewal offer and signing workflow",
        ),
    ],

    compliance=[
        ComplianceRule(
            "Fair Housing Act",
            "No discrimination by protected class in search, listing, or transaction",
            [],
            "mandatory",
            "Never allow filtering by race, color, national origin, religion, sex, disability, "
            "or familial status; audit all search query parameters",
        ),
        ComplianceRule(
            "RESPA",
            "Settlement costs disclosure required before closing",
            ["sale_price_cents", "earnest_money_cents", "escrow_company"],
            "mandatory",
            "Generate Loan Estimate and Closing Disclosure documents; 3-day review period required",
        ),
        ComplianceRule(
            "State Disclosure Laws",
            "Material property defects must be disclosed to buyers",
            ["Inspection.findings"],
            "mandatory",
            "Inspection findings must be shared with buyer before contingency deadline",
        ),
    ],

    api_patterns=[
        "MLS integration (RETS/RESO Web API)",
        "Property search with geographic filtering",
        "Automated Valuation Model (AVM) integration",
        "Escrow status webhooks",
        "Lease renewal automation",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="OfferToContractFlow",
            trigger="user_action",
            trigger_entity="Transaction",
            trigger_condition="status == 'offer_submitted'",
            description="Validate offer, notify seller, update listing, and move to under_contract.",
            services_required=[
                "TransactionService", "ListingService", "NotificationService",
            ],
            integrations_required=[],
            steps=[
                ProcessStep(
                    name="validate_offer",
                    action_type="service_call",
                    service="TransactionService",
                    method="validate_offer",
                    input_mapping={
                        "property_id": "entity.property_id",
                        "sale_price_cents": "entity.sale_price_cents",
                        "earnest_money_cents": "entity.earnest_money_cents",
                    },
                    on_success="notify_seller",
                    on_failure="FAIL",
                    description="Validate offer amount and earnest money requirements",
                ),
                ProcessStep(
                    name="notify_seller",
                    action_type="notification",
                    service="NotificationService",
                    method="send_offer_received",
                    input_mapping={
                        "seller_id": "entity.seller_id",
                        "property_id": "entity.property_id",
                        "sale_price_cents": "entity.sale_price_cents",
                    },
                    on_success="update_listing_status",
                    on_failure="SKIP",
                    description="Notify seller of incoming offer",
                ),
                ProcessStep(
                    name="update_listing_status",
                    action_type="service_call",
                    service="ListingService",
                    method="set_pending",
                    input_mapping={"property_id": "entity.property_id"},
                    on_success="mark_under_contract",
                    on_failure="SKIP",
                    description="Update MLS listing to pending status",
                ),
                ProcessStep(
                    name="mark_under_contract",
                    action_type="state_transition",
                    service="Transaction",
                    method="status",
                    input_mapping={"status": "'under_contract'"},
                    on_success="END",
                    on_failure="FAIL",
                    description="Move transaction to under_contract after seller acceptance",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is a real estate platform. Fair housing laws prohibit discriminatory filtering — "
        "never allow filtering by demographic characteristics. "
        "Transaction dates are legally binding — deadlines must trigger automated notifications. "
        "All party PII (buyer, seller, tenant) is sensitive and must be encrypted at rest."
    ),
)
