"""Fintech domain knowledge pack — PCI-DSS, double-entry ledger, KYC/AML."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="fintech",
    display_name="FinTech / Financial Services",

    entities=[
        EntityTemplate(
            name="Account", table="accounts",
            description="User financial account (wallet, bank account, sub-account)",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("account_type", "string"),       # checking | savings | wallet
                FieldDef("currency", "string"),            # ISO 4217
                FieldDef("balance_cents", "int"),          # always store in minor units
                FieldDef("status", "string"),              # active | frozen | closed
                FieldDef("iban", "string", pii=True, encrypted_at_rest=True),
            ],
            indexes=["user_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Transaction", table="transactions",
            description="Immutable ledger event — never updated, only inserted",
            fields=[
                FieldDef("idempotency_key", "string"),     # caller-supplied, unique
                FieldDef("from_account_id", "fk"),
                FieldDef("to_account_id", "fk"),
                FieldDef("amount_cents", "int"),
                FieldDef("currency", "string"),
                FieldDef("type", "string"),                # credit | debit | transfer | refund
                FieldDef("status", "string"),
                FieldDef("reference", "string"),
                FieldDef("metadata", "text"),
            ],
            indexes=["idempotency_key", "from_account_id", "to_account_id", "status"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="LedgerEntry", table="ledger_entries",
            description="Double-entry bookkeeping line — every transaction produces two entries",
            fields=[
                FieldDef("transaction_id", "fk"),
                FieldDef("account_id", "fk"),
                FieldDef("debit_cents", "int"),
                FieldDef("credit_cents", "int"),
                FieldDef("running_balance_cents", "int"),
                FieldDef("posted_at", "datetime"),
            ],
            indexes=["transaction_id", "account_id", "posted_at"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="KYCRecord", table="kyc_records",
            description="Know-Your-Customer identity verification record",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("full_name", "string", pii=True, encrypted_at_rest=True),
                FieldDef("date_of_birth", "datetime", pii=True, encrypted_at_rest=True),
                FieldDef("national_id", "string", pii=True, encrypted_at_rest=True),
                FieldDef("document_type", "string"),
                FieldDef("status", "string"),              # pending | approved | rejected | expired
                FieldDef("risk_level", "string"),          # low | medium | high
                FieldDef("reviewed_by", "string"),
                FieldDef("reviewed_at", "datetime"),
            ],
            indexes=["user_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="PaymentMethod", table="payment_methods",
            description="Stored payment instrument (tokenised — never raw card data)",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("provider", "string"),            # stripe | paypal | bank_transfer
                FieldDef("provider_token", "string", pci=True, encrypted_at_rest=True),
                FieldDef("last_four", "string", pci=True),
                FieldDef("card_brand", "string"),
                FieldDef("expiry_month", "int", pci=True),
                FieldDef("expiry_year", "int", pci=True),
                FieldDef("is_default", "bool"),
            ],
            indexes=["user_id"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="PaymentFlow",
            entity="Transaction", field="status",
            states=["initiated", "processing", "settled", "failed", "refund_requested", "refunded"],
            transitions={
                "initiated":         ["processing", "failed"],
                "processing":        ["settled", "failed"],
                "settled":           ["refund_requested"],
                "failed":            [],
                "refund_requested":  ["refunded", "failed"],
                "refunded":          [],
            },
            terminal_states=["settled", "failed", "refunded"],
            description="Payment state machine — transitions must be idempotent",
        ),
        WorkflowTemplate(
            name="KYCFlow",
            entity="KYCRecord", field="status",
            states=["submitted", "under_review", "approved", "rejected", "expired"],
            transitions={
                "submitted":    ["under_review"],
                "under_review": ["approved", "rejected"],
                "approved":     ["expired"],
                "rejected":     ["submitted"],
                "expired":      ["submitted"],
            },
            terminal_states=["approved", "rejected"],
            description="KYC verification lifecycle",
        ),
    ],

    compliance=[
        ComplianceRule("PCI-DSS", "Never store raw card numbers, CVV, or full track data",
                       ["card_number", "cvv", "track_data"], "mandatory",
                       "Store only Stripe/PayPal tokenised references"),
        ComplianceRule("PCI-DSS", "Encrypt card-adjacent PII at rest",
                       ["provider_token", "last_four", "expiry_month", "expiry_year"], "mandatory",
                       "Use AES-256 or KMS-managed keys"),
        ComplianceRule("PCI-DSS", "All transaction data access must be logged", [], "mandatory",
                       "Audit trail with user_id, timestamp, action on every mutation"),
        ComplianceRule("AML", "Transactions above threshold must trigger AML check",
                       ["amount_cents"], "mandatory",
                       "Flag transactions > 10,000 USD equivalent for review"),
        ComplianceRule("GDPR", "PII fields (name, DOB, national_id) must be encryptable and deletable",
                       ["full_name", "date_of_birth", "national_id", "iban"], "mandatory",
                       "Support right-to-erasure via pseudonymisation or key deletion"),
    ],

    api_patterns=[
        "POST /payments — create payment with idempotency_key",
        "GET /accounts/{id}/transactions?page=&limit= — paginated ledger",
        "POST /kyc/submit — initiate KYC with document upload",
        "GET /kyc/status — poll KYC status for authenticated user",
        "POST /webhooks/stripe — receive Stripe payment events",
        "GET /accounts/{id}/balance — real-time balance (READ from ledger sum)",
    ],

    prompt_injection="""FINTECH DOMAIN RULES (mandatory — do not omit):
1. Store all monetary values as INTEGER cents/minor units — never use float for money.
2. Every financial transaction MUST use an idempotency_key to prevent double-charges.
3. Use double-entry bookkeeping: every transaction creates BOTH a debit and credit LedgerEntry.
4. Transaction records are IMMUTABLE — never UPDATE or DELETE a transaction row. Issue a reversal instead.
5. Database transactions for money movement MUST use SERIALIZABLE isolation level.
6. Never store raw card numbers, CVV, or magnetic stripe data. Use payment provider tokens only.
7. PII fields (name, DOB, national_id) must be encrypted at rest (AES-256 or KMS).
8. All account and transaction mutations must write to an audit_log table.
9. KYC verification must be completed before allowing transactions above the threshold.
10. API responses must never return full card numbers — return last_four only.
""",

    pipelines=[
        BusinessProcessPipeline(
            name="PaymentProcessingFlow",
            trigger="user_action",
            trigger_entity="Transaction",
            trigger_condition="status == 'pending'",
            description="Full payment execution pipeline: idempotency guard, fraud scoring, "
                        "authorization, double-entry ledger posting, balance update, settlement, "
                        "receipt delivery, and batch registration.",
            services_required=[
                "IdempotencyService", "FraudService", "PaymentGatewayService",
                "LedgerService", "AccountService", "SettlementService", "NotificationService",
            ],
            integrations_required=["stripe", "sendgrid"],
            steps=[
                ProcessStep(
                    name="check_idempotency",
                    action_type="service_call",
                    service="IdempotencyService",
                    method="check_key",
                    input_mapping={"idempotency_key": "entity.idempotency_key"},
                    on_success="run_fraud_check",
                    on_failure="SKIP",
                    description="Return cached result if this idempotency_key was already processed",
                ),
                ProcessStep(
                    name="run_fraud_check",
                    action_type="service_call",
                    service="FraudService",
                    method="score",
                    input_mapping={
                        "amount_cents": "entity.amount_cents",
                        "from_account_id": "entity.from_account_id",
                        "metadata": "entity.metadata",
                    },
                    on_success="authorize_payment",
                    on_failure="FAIL",
                    timeout_seconds=10,
                    description="ML fraud score; reject if score exceeds threshold",
                ),
                ProcessStep(
                    name="authorize_payment",
                    action_type="external_api",
                    service="PaymentGatewayService",
                    method="authorize",
                    input_mapping={
                        "amount_cents": "entity.amount_cents",
                        "currency": "entity.currency",
                        "payment_method_id": "entity.from_account_id",
                    },
                    on_success="post_ledger_entries",
                    on_failure="FAIL",
                    compensation="void_authorization",
                    retry_count=2,
                    timeout_seconds=30,
                    description="Authorize charge via Stripe; obtain authorization_code",
                ),
                ProcessStep(
                    name="post_ledger_entries",
                    action_type="service_call",
                    service="LedgerService",
                    method="post_double_entry",
                    input_mapping={
                        "transaction_id": "entity.id",
                        "amount_cents": "entity.amount_cents",
                        "from_account_id": "entity.from_account_id",
                        "to_account_id": "entity.to_account_id",
                    },
                    on_success="update_balances",
                    on_failure="FAIL",
                    compensation="reverse_ledger_entries",
                    description="Insert debit + credit LedgerEntry rows in a SERIALIZABLE transaction",
                ),
                ProcessStep(
                    name="update_balances",
                    action_type="service_call",
                    service="AccountService",
                    method="update_balance",
                    input_mapping={
                        "from_account_id": "entity.from_account_id",
                        "to_account_id": "entity.to_account_id",
                        "amount_cents": "entity.amount_cents",
                    },
                    on_success="settle_transaction",
                    on_failure="FAIL",
                    compensation="reverse_balance_update",
                    description="Atomically decrement sender and increment receiver balance",
                ),
                ProcessStep(
                    name="settle_transaction",
                    action_type="state_transition",
                    service="Transaction",
                    method="status",
                    input_mapping={"status": "'settled'"},
                    on_success="send_receipt",
                    on_failure="FAIL",
                    description="Mark Transaction as settled — this is the commit point",
                ),
                ProcessStep(
                    name="send_receipt",
                    action_type="notification",
                    service="NotificationService",
                    method="send_receipt",
                    input_mapping={
                        "transaction_id": "entity.id",
                        "user_id": "entity.from_account_id",
                        "amount_cents": "entity.amount_cents",
                    },
                    on_success="add_to_settlement_batch",
                    on_failure="SKIP",
                    description="Email transaction receipt via SendGrid — non-fatal",
                ),
                ProcessStep(
                    name="add_to_settlement_batch",
                    action_type="batch",
                    service="SettlementService",
                    method="add_to_batch",
                    input_mapping={"transaction_id": "entity.id"},
                    on_success="END",
                    on_failure="SKIP",
                    description="Queue transaction for end-of-day settlement batch with acquirer",
                ),
            ],
        ),
    ],
)
