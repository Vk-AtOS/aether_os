"""SaaS / multi-tenant domain knowledge pack — tenancy, billing, webhooks, SOC2."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    ComplianceRule, DomainKnowledgePack, EntityTemplate, FieldDef, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="saas_multitenant",
    display_name="SaaS / Multi-Tenant Platform",

    entities=[
        EntityTemplate(
            name="Organisation", table="organisations",
            description="Top-level tenant — the billing entity that owns all data within it",
            fields=[
                FieldDef("name", "string"),
                FieldDef("slug", "string"),               # URL-safe identifier — immutable after creation
                FieldDef("plan_id", "fk"),
                FieldDef("status", "string"),             # trialing | active | past_due | cancelled | suspended
                FieldDef("stripe_customer_id", "string"),
                FieldDef("trial_ends_at", "datetime", required=False),
                FieldDef("billing_email", "string", pii=True),
                FieldDef("max_seats", "int"),
                FieldDef("max_api_calls_per_month", "int"),
                FieldDef("data_region", "string"),        # us-east-1 | eu-west-1 | ap-southeast-1
            ],
            indexes=["slug", "status", "stripe_customer_id"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Member", table="members",
            description="A user's membership and role within an organisation",
            fields=[
                FieldDef("org_id", "fk"),
                FieldDef("user_id", "fk"),
                FieldDef("role", "string"),               # owner | admin | member | viewer
                FieldDef("status", "string"),             # active | suspended | invited
                FieldDef("invited_by", "fk", required=False),
                FieldDef("joined_at", "datetime", required=False),
            ],
            indexes=["org_id", "user_id", "role", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Plan", table="plans",
            description="Subscription tier definition — defines limits and pricing",
            fields=[
                FieldDef("name", "string"),               # free | starter | pro | enterprise
                FieldDef("stripe_price_id", "string"),
                FieldDef("price_cents", "int"),
                FieldDef("billing_period", "string"),     # monthly | annual
                FieldDef("max_seats", "int"),
                FieldDef("max_api_calls_per_month", "int"),
                FieldDef("max_storage_gb", "int"),
                FieldDef("features", "text"),             # JSON feature flag map
                FieldDef("is_public", "bool"),
            ],
            indexes=["name", "is_public"],
        ),
        EntityTemplate(
            name="Subscription", table="subscriptions",
            description="Stripe subscription record linked to an organisation",
            fields=[
                FieldDef("org_id", "fk"),
                FieldDef("plan_id", "fk"),
                FieldDef("stripe_subscription_id", "string"),
                FieldDef("status", "string"),             # trialing | active | past_due | cancelled | unpaid
                FieldDef("current_period_start", "datetime"),
                FieldDef("current_period_end", "datetime"),
                FieldDef("cancel_at_period_end", "bool"),
                FieldDef("cancelled_at", "datetime", required=False),
            ],
            indexes=["org_id", "stripe_subscription_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="UsageRecord", table="usage_records",
            description="Per-organisation usage meter entry for billing and limit enforcement",
            fields=[
                FieldDef("org_id", "fk"),
                FieldDef("metric", "string"),             # api_calls | storage_gb | seats | ai_tokens
                FieldDef("quantity", "int"),
                FieldDef("recorded_at", "datetime"),
                FieldDef("billing_period_start", "datetime"),
            ],
            indexes=["org_id", "metric", "billing_period_start"],
            soft_delete=False,                            # usage records are append-only
        ),
        EntityTemplate(
            name="WebhookEndpoint", table="webhook_endpoints",
            description="Customer-registered endpoint for event delivery",
            fields=[
                FieldDef("org_id", "fk"),
                FieldDef("url", "string"),
                FieldDef("secret", "string", encrypted_at_rest=True),  # HMAC signing secret
                FieldDef("events", "text"),               # JSON array of subscribed event types
                FieldDef("status", "string"),             # active | paused | disabled
                FieldDef("failure_count", "int"),
                FieldDef("last_success_at", "datetime", required=False),
                FieldDef("last_failure_at", "datetime", required=False),
            ],
            indexes=["org_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="WebhookDelivery", table="webhook_deliveries",
            description="Individual webhook dispatch attempt and its outcome",
            fields=[
                FieldDef("endpoint_id", "fk"),
                FieldDef("event_type", "string"),
                FieldDef("payload", "text"),              # JSON event body
                FieldDef("status", "string"),             # pending | delivered | failed
                FieldDef("http_status", "int", required=False),
                FieldDef("response_body", "text", required=False),
                FieldDef("attempt_number", "int"),
                FieldDef("next_retry_at", "datetime", required=False),
            ],
            indexes=["endpoint_id", "status", "next_retry_at"],
        ),
        EntityTemplate(
            name="AuditLog", table="audit_logs",
            description="Immutable record of all user actions within an org (SOC2 requirement)",
            fields=[
                FieldDef("org_id", "fk"),
                FieldDef("user_id", "fk"),
                FieldDef("action", "string"),             # e.g. member.invite, plan.upgrade, api_key.delete
                FieldDef("resource_type", "string"),
                FieldDef("resource_id", "string"),
                FieldDef("ip_address", "string"),
                FieldDef("user_agent", "string"),
                FieldDef("metadata", "text"),             # JSON context
                FieldDef("occurred_at", "datetime"),
            ],
            indexes=["org_id", "user_id", "action", "occurred_at"],
            soft_delete=False,                            # audit logs are immutable
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="SubscriptionLifecycle",
            entity="Subscription", field="status",
            states=["trialing", "active", "past_due", "unpaid", "cancelled"],
            transitions={
                "trialing": ["active", "cancelled"],
                "active":   ["past_due", "cancelled"],
                "past_due": ["active", "unpaid", "cancelled"],
                "unpaid":   ["active", "cancelled"],
                "cancelled": [],
            },
            terminal_states=["cancelled"],
            description="Stripe-driven subscription state — sync via webhook events",
        ),
        WorkflowTemplate(
            name="WebhookDelivery",
            entity="WebhookDelivery", field="status",
            states=["pending", "delivered", "failed"],
            transitions={
                "pending":   ["delivered", "failed"],
                "failed":    ["pending"],                 # retry
                "delivered": [],
            },
            terminal_states=["delivered"],
            description="Exponential backoff retry for webhook delivery",
        ),
    ],

    compliance=[
        ComplianceRule("SOC2", "All user actions within an org must be recorded in immutable audit log",
                       [], "mandatory",
                       "AuditLog table append-only; no UPDATE/DELETE; retain 1 year minimum"),
        ComplianceRule("SOC2", "Row-level security: every DB query must filter by org_id",
                       ["org_id"], "mandatory",
                       "Apply org_id tenant scope at ORM/query layer — never rely on app logic alone"),
        ComplianceRule("SOC2", "Webhook secrets must be encrypted at rest and used for HMAC-SHA256 signatures",
                       ["secret"], "mandatory",
                       "Sign every webhook payload with HMAC-SHA256; include X-Signature header"),
        ComplianceRule("GDPR", "Org data deletion must cascade to all PII and be auditable",
                       ["billing_email", "org_id"], "mandatory",
                       "Soft delete org + schedule data purge job after 30-day grace period"),
        ComplianceRule("GDPR", "Data residency: store data in the region the org selected at signup",
                       ["data_region"], "mandatory",
                       "Route DB writes to region-specific connection pool based on org.data_region"),
        ComplianceRule("SECURITY", "API keys must be hashed with bcrypt before storage",
                       ["secret"], "mandatory",
                       "Store only bcrypt hash of API key; display raw key only once at creation"),
    ],

    api_patterns=[
        "POST /organisations — create org with initial owner member",
        "GET /organisations/{slug}/members — list members with roles",
        "POST /organisations/{slug}/members/invite — send invitation email",
        "GET /billing/plans — list public plans with features",
        "POST /billing/subscribe — create Stripe subscription",
        "POST /billing/portal — redirect to Stripe customer portal",
        "POST /webhooks/stripe — receive Stripe billing events (subscription.updated, invoice.paid)",
        "GET /usage?metric=api_calls&period=current — usage vs plan limits",
        "POST /webhook-endpoints — register customer webhook URL",
        "GET /audit-logs?from=&to=&user_id= — paginated audit trail (admin only)",
    ],

    prompt_injection="""SAAS MULTI-TENANT DOMAIN RULES (mandatory — SOC2 compliance required):
1. EVERY database query MUST include an org_id filter — no cross-tenant data leakage ever.
2. Row-level security must be enforced at the query layer, not the application layer.
3. Webhook payloads MUST be signed with HMAC-SHA256 using the endpoint secret — include X-Webhook-Signature header.
4. Webhook delivery must use exponential backoff with at least 5 retry attempts before disabling the endpoint.
5. Usage limits (API calls, seats, storage) must be checked BEFORE serving the request — return 429 when exceeded.
6. Billing changes (plan upgrades/downgrades) must be driven by Stripe webhook events — never trust client-side plan claims.
7. All user actions within an org must be appended to audit_logs — immutable, no UPDATE or DELETE ever.
8. API keys must be hashed with bcrypt before storage — display the raw key exactly once at creation, then never again.
9. Data residency: route every DB query to the org's selected data_region — enforce at connection pool level.
10. Org deletion is a soft delete + 30-day grace period — schedule a background purge job, not an immediate delete.
""",
)
