"""
SaaS Domain Pack for AetherOS.

Carries canonical entity graph, multi-tenant constraints, integrations, and
seed patterns for generating correct B2B SaaS backends and frontends.
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
        name="Organization",
        description=(
            "Top-level tenant unit. All other models carry an org_id FK. "
            "Plan tier gates feature access."
        ),
        typical_fields=[
            "id", "name", "slug",
            "plan_tier",  # Enum: free / starter / professional / enterprise
            "billing_email",
            "stripe_customer_id",
            "api_calls_count",      # usage tracking
            "storage_bytes_used",   # BigInteger
            "max_api_calls",        # plan quota
            "max_storage_bytes",    # plan quota
            "last_active_at",
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["slug", "stripe_customer_id"],
        fk_relationships=[],
        compliance_fields=["stripe_customer_id"],
        indexes=["slug", "plan_tier", "is_active"],
    ),
    EntitySpec(
        name="Subscription",
        description=(
            "Billing subscription for an Organization. Tracks plan, cycle, "
            "and Stripe subscription reference. Status gates access."
        ),
        typical_fields=[
            "id", "org_id",
            "plan_tier",   # Enum: free / starter / professional / enterprise
            "billing_cycle",  # Enum: monthly / annual
            "status",   # active / trialing / past_due / cancelled / unpaid
            "stripe_subscription_id",
            "stripe_price_id",
            "current_period_start", "current_period_end",
            "trial_ends_at",
            "cancelled_at",
            "created_at", "updated_at",
        ],
        unique_fields=["stripe_subscription_id"],
        fk_relationships=["org_id -> Organization.id"],
        compliance_fields=["stripe_subscription_id"],
        indexes=["org_id", "status", "plan_tier", "current_period_end"],
    ),
    EntitySpec(
        name="Feature",
        description=(
            "A named platform capability gated by plan tier. "
            "Used by check_plan_feature() to authorize access."
        ),
        typical_fields=[
            "id", "key",   # unique feature key e.g. 'advanced_analytics'
            "name", "description",
            "min_plan_tier",  # minimum plan required: Enum matching plan_tier
            "is_active",
            "created_at",
        ],
        unique_fields=["key"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["key", "min_plan_tier", "is_active"],
    ),
    EntitySpec(
        name="UsageRecord",
        description=(
            "Per-period usage event for an Organization. "
            "Used for billing, quota enforcement, and analytics."
        ),
        typical_fields=[
            "id", "org_id",
            "metric",   # e.g. 'api_calls' / 'storage_bytes' / 'active_users'
            "value",    # Numeric(18,6)
            "period_start", "period_end",
            "stripe_usage_record_id",  # for metered billing
            "created_at",
        ],
        unique_fields=[],
        fk_relationships=["org_id -> Organization.id"],
        compliance_fields=[],
        indexes=["org_id", "metric", "period_start"],
    ),
    EntitySpec(
        name="APIKey",
        description=(
            "Programmatic access credential for an Organization. "
            "key_hash stored as bcrypt hash — plaintext returned only once at creation."
        ),
        typical_fields=[
            "id", "org_id",
            "name",  # human-readable label e.g. 'production-key'
            "key_prefix",  # first 8 chars shown in UI e.g. 'ak_live_'
            "key_hash",    # bcrypt hash of full key — NEVER store plaintext
            "scopes_json",  # list of allowed scopes e.g. ['read', 'write']
            "last_used_at",
            "expires_at",  # nullable — None means never expires
            "is_active",
            "created_at",
        ],
        unique_fields=["key_prefix"],
        fk_relationships=["org_id -> Organization.id"],
        compliance_fields=["key_hash"],  # stored as hash, never plaintext
        indexes=["org_id", "key_prefix", "is_active"],
    ),
    EntitySpec(
        name="Webhook",
        description=(
            "Outbound webhook endpoint registered by an Organization. "
            "Each delivery is signed with HMAC-SHA256 using a secret stored hashed."
        ),
        typical_fields=[
            "id", "org_id",
            "url",
            "events_json",   # list of event types to send e.g. ['user.created']
            "secret_hash",   # HMAC signing secret — stored as bcrypt hash
            "is_active",
            "failure_count",  # consecutive delivery failures
            "last_triggered_at",
            "created_at", "updated_at",
        ],
        unique_fields=[],
        fk_relationships=["org_id -> Organization.id"],
        compliance_fields=["secret_hash"],  # HMAC secret — never in plaintext
        indexes=["org_id", "is_active"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="stripe",
        purpose="Subscription billing, plan upgrades, metered usage billing, payment method management",
        env_vars=["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"],
        typical_methods=[
            "stripe.Customer.create",
            "stripe.Subscription.create",
            "stripe.Subscription.modify",
            "stripe.Subscription.cancel",
            "stripe.UsageRecord.create",
            "stripe.BillingPortal.Session.create",
        ],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Trial expiry reminders, plan upgrade prompts, usage limit warnings, invoice delivery",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_trial_expiry_reminder",
            "send_plan_upgrade_prompt",
            "send_usage_limit_warning",
            "send_invoice",
            "send_payment_failed",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # Multi-tenancy
    "org_id (UUID, ForeignKey('organizations.id'), nullable=False) MUST be present on EVERY ORM model — no data is org-agnostic.",
    "Every list endpoint MUST filter by org_id from the authenticated user's context — NEVER return cross-org data.",
    "org_id must be injected from the authenticated user's context, never accepted as a client-supplied query parameter.",
    # Plan tier gating
    "plan_tier MUST be an Enum: free / starter / professional / enterprise — never a raw string.",
    "Feature access MUST be checked via check_plan_feature(org, feature_key) in a separate helpers.py — never inline ad-hoc tier checks.",
    "Quota enforcement: check api_calls_count < max_api_calls before processing API requests — return HTTP 429 with plan upgrade prompt when exceeded.",
    # API keys
    "APIKey MUST be stored as a bcrypt hash (key_hash) — never store the plaintext API key in the database.",
    "Return the plaintext API key exactly once, at creation time, in a CreatedAPIKey response model — never again after that.",
    "API key prefix (first 8 chars) is stored unmasked for display in the UI — the rest is never recoverable.",
    # Webhooks
    "Webhook deliveries MUST be signed with HMAC-SHA256 using the webhook secret — include X-Signature header on every outbound request.",
    "Webhook secret MUST be stored as a hash — the raw secret is returned once at creation only.",
    "Disable webhook (is_active=False) after 5 consecutive delivery failures — log failure_count increment on each failure.",
    # Subscriptions
    "Subscription records MUST track: plan_tier, billing_cycle (monthly/annual), current_period_start, current_period_end, stripe_subscription_id.",
    "Access to paid features MUST check subscription.status in ('active', 'trialing') — reject with HTTP 402 and upgrade URL otherwise.",
    "UsageRecord values MUST use Numeric(18,6) — never plain int or float for metered billing.",
    "Every Organization MUST have usage tracking: api_calls_count, storage_bytes_used, last_active_at.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "slug": "org-{i}",
    "name": "Acme Corp {i}|Globex Inc {i}|Initech Ltd {i}|Umbrella Co {i}|Hooli {i}",
    "plan_tier": "free|starter|professional|enterprise",
    "billing_cycle": "monthly|annual",
    "status_subscription": "active|trialing|past_due|cancelled",
    "stripe_customer_id": "cus_test_{i:016d}",
    "stripe_subscription_id": "sub_test_{i:016d}",
    "stripe_price_id": "price_test_{i:016d}",
    "key_prefix": "ak_live_{i:08d}",
    "metric": "api_calls|storage_bytes|active_users|webhooks_sent",
    "email": "admin_{i}@example.com",
    "feature_key": "advanced_analytics|custom_domain|sso|audit_log|api_access|webhooks",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Multi-tenancy: inject org_id from JWT claims in a reusable FastAPI dependency (get_current_org) — never trust client-supplied org_id.",
    "Feature gating: implement check_plan_feature(org: Organization, feature_key: str) -> bool in helpers.py; raise HTTP 402 with upgrade_url on False.",
    "Quota enforcement: maintain api_calls_count with atomic increment (UPDATE organizations SET api_calls_count = api_calls_count + 1) to avoid race conditions.",
    "API key lifecycle: generate a cryptographically random 32-byte key, return it once, store only the bcrypt hash and first-8-char prefix.",
    "Webhook delivery: use a background task queue (FastAPI BackgroundTasks or Celery) for webhook delivery — never block the request-response cycle.",
    "Stripe billing portal: use stripe.BillingPortal.Session.create to let customers manage their own subscriptions without custom UI.",
    "Trial enforcement: when trial_ends_at passes, downgrade plan_tier to 'free' via a scheduled background task — do not gate solely on trial_ends_at date check.",
    "Stripe webhooks: handle subscription.updated, invoice.payment_failed, customer.subscription.deleted to keep local subscription records in sync.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

SAAS_PACK = DomainPack(
    domain="saas",
    display_name="B2B SaaS Platform",
    description=(
        "Multi-tenant B2B SaaS platform supporting organizations, subscriptions, "
        "feature gating by plan tier, API keys, webhooks, and metered usage billing."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["SOC2"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["SAAS_PACK"]
