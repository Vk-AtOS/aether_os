"""ERP domain knowledge pack — GL, cost centres, procurement, SOX compliance."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    ComplianceRule, DomainKnowledgePack, EntityTemplate, FieldDef, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="erp",
    display_name="ERP / Enterprise Resource Planning",

    entities=[
        EntityTemplate(
            name="GLAccount", table="gl_accounts",
            description="General Ledger account in the chart of accounts",
            fields=[
                FieldDef("account_code", "string"),       # e.g. 1000, 2100, 5010
                FieldDef("name", "string"),
                FieldDef("account_type", "string"),       # asset | liability | equity | revenue | expense
                FieldDef("parent_id", "fk", required=False),
                FieldDef("is_control_account", "bool"),
                FieldDef("currency", "string"),
                FieldDef("status", "string"),             # active | inactive
            ],
            indexes=["account_code", "account_type"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="CostCentre", table="cost_centres",
            description="Organisational unit for budget tracking and cost allocation",
            fields=[
                FieldDef("code", "string"),
                FieldDef("name", "string"),
                FieldDef("parent_id", "fk", required=False),
                FieldDef("manager_id", "fk"),
                FieldDef("budget_cents", "int"),
                FieldDef("fiscal_year", "int"),
                FieldDef("department", "string"),
                FieldDef("status", "string"),
            ],
            indexes=["code", "department"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="JournalEntry", table="journal_entries",
            description="Double-entry bookkeeping record — immutable once posted",
            fields=[
                FieldDef("entry_number", "string"),       # unique reference
                FieldDef("entry_date", "datetime"),
                FieldDef("description", "text"),
                FieldDef("reference", "string"),
                FieldDef("status", "string"),             # draft | posted | reversed
                FieldDef("posted_by", "fk"),
                FieldDef("posted_at", "datetime", required=False),
                FieldDef("period_id", "fk"),
                FieldDef("total_debit_cents", "int"),
                FieldDef("total_credit_cents", "int"),    # must equal total_debit_cents
            ],
            indexes=["entry_number", "entry_date", "status"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="JournalLine", table="journal_lines",
            description="Individual debit or credit line within a journal entry",
            fields=[
                FieldDef("journal_entry_id", "fk"),
                FieldDef("gl_account_id", "fk"),
                FieldDef("cost_centre_id", "fk", required=False),
                FieldDef("debit_cents", "int"),
                FieldDef("credit_cents", "int"),
                FieldDef("description", "string"),
                FieldDef("currency", "string"),
                FieldDef("exchange_rate", "float", required=False),
            ],
            indexes=["journal_entry_id", "gl_account_id"],
        ),
        EntityTemplate(
            name="PurchaseOrder", table="purchase_orders",
            description="Formal procurement request to a vendor",
            fields=[
                FieldDef("po_number", "string"),
                FieldDef("vendor_id", "fk"),
                FieldDef("requester_id", "fk"),
                FieldDef("approver_id", "fk", required=False),
                FieldDef("cost_centre_id", "fk"),
                FieldDef("status", "string"),
                FieldDef("currency", "string"),
                FieldDef("total_cents", "int"),
                FieldDef("required_by_date", "datetime", required=False),
                FieldDef("notes", "text", required=False),
            ],
            indexes=["po_number", "vendor_id", "status"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="Vendor", table="vendors",
            description="Supplier or service provider",
            fields=[
                FieldDef("name", "string"),
                FieldDef("tax_id", "string"),
                FieldDef("payment_terms", "string"),      # net_30 | net_60 | due_on_receipt
                FieldDef("currency", "string"),
                FieldDef("bank_account", "string", pii=True, encrypted_at_rest=True),
                FieldDef("contact_email", "string", pii=True),
                FieldDef("status", "string"),
            ],
            indexes=["name", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="FiscalPeriod", table="fiscal_periods",
            description="Accounting period — controls when journals can be posted",
            fields=[
                FieldDef("name", "string"),               # e.g. "2026-Q1", "2026-01"
                FieldDef("fiscal_year", "int"),
                FieldDef("period_number", "int"),
                FieldDef("start_date", "datetime"),
                FieldDef("end_date", "datetime"),
                FieldDef("status", "string"),             # open | closed | locked
            ],
            indexes=["fiscal_year", "status"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="PurchaseOrderApproval",
            entity="PurchaseOrder", field="status",
            states=["draft", "submitted", "under_review", "approved", "rejected",
                    "sent_to_vendor", "partially_received", "received", "cancelled"],
            transitions={
                "draft":              ["submitted"],
                "submitted":          ["under_review", "approved", "rejected"],
                "under_review":       ["approved", "rejected"],
                "approved":           ["sent_to_vendor", "cancelled"],
                "rejected":           ["draft"],
                "sent_to_vendor":     ["partially_received", "received"],
                "partially_received": ["received"],
                "received":           [],
                "cancelled":          [],
            },
            terminal_states=["received", "cancelled"],
            description="Multi-level procurement approval — delegates by amount threshold",
        ),
        WorkflowTemplate(
            name="JournalApproval",
            entity="JournalEntry", field="status",
            states=["draft", "submitted", "posted", "reversed"],
            transitions={
                "draft":     ["submitted"],
                "submitted": ["posted", "draft"],
                "posted":    ["reversed"],
                "reversed":  [],
            },
            terminal_states=["posted", "reversed"],
            description="Journal entry must be approved before posting to GL",
        ),
    ],

    compliance=[
        ComplianceRule("SOX", "All journal entries require dual-control — maker/checker separation",
                       ["posted_by"], "mandatory",
                       "Submitter and approver must be different users; enforce in API gate"),
        ComplianceRule("SOX", "Fiscal periods must lock after close — no retroactive postings",
                       ["status"], "mandatory",
                       "Reject journal entries where period.status == closed or locked"),
        ComplianceRule("SOX", "Audit trail required on all GL mutations with user and timestamp",
                       [], "mandatory",
                       "Append-only audit_log table; never UPDATE or DELETE journal lines"),
        ComplianceRule("SOX", "Segregation of duties — approvers cannot approve their own POs",
                       ["requester_id", "approver_id"], "mandatory",
                       "Assert requester_id != approver_id in the approval API endpoint"),
        ComplianceRule("GDPR", "Vendor PII (bank account, contact) must be encryptable",
                       ["bank_account", "contact_email"], "mandatory",
                       "AES-256 at rest; support right-to-erasure for vendor contacts"),
        ComplianceRule("IFRS", "All monetary amounts stored in minor units (cents) with explicit currency",
                       ["total_cents", "debit_cents", "credit_cents", "budget_cents"], "mandatory",
                       "Currency + amount pair on every monetary field; never store as float"),
    ],

    api_patterns=[
        "GET /gl/accounts?type=expense&status=active — chart of accounts",
        "POST /gl/journal-entries — create draft journal (debit must equal credit)",
        "POST /gl/journal-entries/{id}/post — submit for approval",
        "GET /gl/trial-balance?period_id= — trial balance report",
        "POST /procurement/purchase-orders — create PO with line items",
        "PUT /procurement/purchase-orders/{id}/approve — approve with threshold check",
        "GET /cost-centres/{id}/budget-vs-actual?fiscal_year= — variance report",
        "POST /periods/{id}/close — close fiscal period (locks all postings)",
    ],

    prompt_injection="""ERP DOMAIN RULES (mandatory — SOX compliance required):
1. Store all monetary amounts as INTEGER cents with an explicit currency field — never use float.
2. Every journal entry MUST balance: sum(debit_cents) == sum(credit_cents) across all journal lines.
3. Journal entries are IMMUTABLE once posted — never UPDATE posted journals. Issue a reversal entry.
4. Enforce maker/checker separation: the user who creates a journal cannot also approve it.
5. Fiscal periods must lock after close — reject any journal with period.status != 'open'.
6. Purchase order approvals must follow delegation-of-authority: amount thresholds per approver role.
7. All GL mutations must write to an append-only audit_log (user_id, action, table, record_id, timestamp).
8. Vendor bank details must be encrypted at rest (AES-256 or KMS); never expose in API responses.
9. Multi-currency: always store source_currency, exchange_rate, and converted amount separately.
10. Budget vs actual variance must be computed from the ledger sum — never cache or pre-aggregate.
""",
)
