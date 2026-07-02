"""Constraint engine — deterministic rule sets injected into every LLM prompt.

The engine compiles per-stack, per-domain constraint blocks so the LLM cannot
hallucinate import paths, invent ORM patterns, or use plaintext passwords.
All rules are hardcoded (no LLM, no external deps).
"""
from __future__ import annotations

from typing import List


class ConstraintEngine:
    """Return constraint lists for backend, seed, and frontend generation."""

    # ── Backend constraints ───────────────────────────────────────────────────

    def get_backend_constraints(self, stack: str = "fastapi") -> List[str]:
        """Return hard constraints for backend code generation."""
        common = [
            "Use absolute imports only — never 'from . import', 'from .. import', or 'from..module import'.",
            "Never use 'import *' — always name every symbol you import.",
            "All SQLAlchemy ORM models must inherit from Base (imported from database.py).",
            "Export 'all_routers: list' from routers/crud.py — main.py iterates it to mount routers.",
            "All passwords must be bcrypt-hashed before storage; never store plaintext.",
            "Every APIRouter must define a 'prefix' and 'tags' argument.",
            "Never redefine symbols that are already declared in the same file.",
            "Every endpoint that modifies data (POST/PUT/PATCH/DELETE) must require auth.",
            "Always include 'from __future__ import annotations' as the first import line.",
            "Return typed Pydantic response models from every endpoint, never raw dicts.",
        ]
        if stack == "fastapi":
            return common + [
                "Import Depends, HTTPException, status from fastapi — not from starlette.",
                "Use 'AsyncSession' from sqlalchemy.ext.asyncio, never the sync Session.",
                "Column definitions must not have duplicate keyword arguments (e.g. two 'default=' values).",
                "Pagination: every list endpoint must accept 'skip: int = 0' and 'limit: int = 100'.",
                "Auth dependency must be 'get_current_user' imported from auth.py (absolute import).",
                "Do not import from 'fastapi.security' directly in crud.py — use the auth.py wrapper.",
            ]
        return common

    # ── Seed constraints ──────────────────────────────────────────────────────

    def get_seed_constraints(self, entities: List[str]) -> List[str]:
        """Return constraints for seed data generation."""
        base = [
            "Generate exactly 20 records per entity — not 5, not 10, exactly 20.",
            "All fields declared unique=True in the model must have unique values across all 20 records.",
            "Email fields: use pattern {entity_lower}_{i}@example.com (e.g. product_1@example.com).",
            "Username fields: use pattern {entity_lower}_user_{i} (e.g. order_user_1).",
            "slug fields: use pattern {entity_lower}-{i} (e.g. product-1, product-2).",
            "file_path fields: use pattern /files/{entity_lower}-{i:03d}.pdf.",
            "Foreign keys must reference IDs that actually exist — generate parent records first.",
            "Never hard-code the same value for a unique field across multiple records.",
            "Passwords in seed data must be bcrypt-hashed using passlib.hash.bcrypt.",
            "Use 'await db.commit()' after every batch insert — do not leave transactions open.",
            "Wrap the entire seed function in try/except so a seed failure never crashes startup.",
        ]
        if entities:
            entity_list = ", ".join(entities)
            base.append(
                f"Generate seed records in dependency order: {entity_list} "
                "(create entities that others FK-reference before the ones that reference them)."
            )
        return base

    # ── Frontend constraints ──────────────────────────────────────────────────

    def get_frontend_constraints(self, stack: str = "react") -> List[str]:
        """Return constraints for frontend code generation."""
        common = [
            "Use absolute imports only — never relative paths like '../../../components/X'.",
            "All API calls must read the base URL from import.meta.env.VITE_API_URL.",
            "Every form must validate required fields before submitting (show inline errors).",
            "A 404 Not Found page must exist and be registered in the router.",
            "Never hard-code 'http://localhost:8000' or any port in source files.",
            "Display a loading state while any async request is in flight.",
            "Show a user-visible error message when an API request fails (not just console.error).",
        ]
        if stack == "react":
            return common + [
                "Use TanStack Router (not react-router-dom) for all routing.",
                "Use TanStack Query (useQuery / useMutation) for all server-state management.",
                "API client must set 'Authorization: Bearer <token>' header from localStorage.",
                "Export every page component as a default export.",
                "Do not import from 'react' directly for hooks — use named imports: import { useState } from 'react'.",
            ]
        return common

    # ── Per-vertical constraints ──────────────────────────────────────────────

    def get_vertical_constraints(self, vertical: str) -> List[str]:
        """Return domain-specific must-follow rules for a vertical."""
        vertical = (vertical or "").lower().strip()

        if vertical == "ecommerce":
            return [
                "Price/amount fields must use Decimal type, not Float — use NUMERIC(12,2) in DB (PCI compliance and precision).",
                "Cart sessions must use UUID primary keys, not sequential integer IDs.",
                "SKU fields must be declared unique=True and indexed=True on the Column definition.",
                "Order status must use a Python Enum: pending / confirmed / shipped / delivered / cancelled — never a free-form string.",
                "Never store raw card data — only store payment_intent_id (str) from Stripe; add a comment '# PCI: no card data stored' near the field.",
                "Inventory quantity must have a DB-level non-negative constraint: CheckConstraint('quantity >= 0', name='ck_quantity_non_negative').",
                "Product price must have a DB-level non-negative constraint: CheckConstraint('price >= 0', name='ck_price_non_negative').",
                "Every Order record must have a unique human-readable reference: ORD-{YYYY}-{N:06d}.",
            ]

        if vertical == "healthcare":
            return [
                "Every ORM model must include: created_by (String, nullable=False, default='system'), updated_by (String, nullable=False, onupdate='system'), accessed_at (DateTime, nullable=True).",
                "Never log PHI (patient name, email, DOB, diagnosis) — add '# HIPAA: never log this field' comment above each PHI column.",
                "Appointment status must be an Enum: scheduled / confirmed / in_progress / completed / cancelled / no_show.",
                "Patient records must include full audit trail columns: created_at, updated_at, created_by, updated_by — all non-nullable where applicable.",
                "File/document attachments must store a storage_path (str) reference only — never store binary file data (BLOB) in the database.",
                "Medical record numbers must follow format MRN-{i:06d} and be unique and indexed.",
                "Every endpoint returning patient data must be gated with role-based access: only 'provider' and 'admin' roles may read PHI.",
            ]

        if vertical == "fintech":
            return [
                "All monetary amount columns must use Numeric(precision=18, scale=6) — never Float or plain Decimal without precision.",
                "Every transaction record must have: reference_id (String, unique=True, indexed=True), status (Enum), created_at (DateTime), completed_at (DateTime, nullable=True).",
                "Implement the ledger pattern: every financial event must produce exactly 2 LedgerEntry rows (one debit, one credit) that sum to zero.",
                "Amount columns must enforce non-negative values at the DB level via CheckConstraint('amount >= 0') — do not rely on application logic alone.",
                "Account balances must be computed from ledger entries (sum of credits minus debits), never stored as a raw mutable column without a reconciliation check.",
                "Transaction reference IDs must follow format TXN-{YYYY}-{i:08d} and be globally unique.",
                "Account numbers must follow format ACC-{i:010d} and be unique and indexed.",
            ]

        if vertical == "ai_integrated":
            return [
                "Vector embedding dimensions must be consistent across the entire project — use 1536 dimensions for OpenAI text-embedding-3-small.",
                "Chunked document records must include: chunk_size (Integer), chunk_index (Integer), source_document_id (FK to documents table) — all non-nullable.",
                "ChatSession records must include: session_id (UUID, primary key), user_id (FK to users), model_name (String), created_at (DateTime) — all non-nullable.",
                "ChatMessage records must include: session_id (FK to chat_sessions), role (Enum: user/assistant/system), content (Text), tokens_used (Integer, nullable), created_at (DateTime).",
                "Embedding columns must use ARRAY(Float) or a vector extension type — never store embeddings as JSON strings.",
                "Knowledge base documents must track embedding_status: Enum('pending', 'indexed', 'failed') — always default to 'pending'.",
                "Search/retrieval endpoints must return relevance scores (0.0–1.0) alongside results — never return raw distance metrics to the client.",
            ]

        if vertical == "saas":
            return [
                "org_id (UUID, ForeignKey('organizations.id'), nullable=False) must be present on EVERY ORM model, not just User — no data is org-agnostic.",
                "plan_tier must be an Enum: free / starter / professional / enterprise — never a raw string.",
                "Every organization must have usage tracking columns: api_calls_count (Integer, default=0), storage_bytes_used (BigInteger, default=0), last_active_at (DateTime, nullable=True).",
                "Every list endpoint must filter by org_id from the authenticated user's context — never return cross-org data.",
                "Feature flags must check plan_tier before granting access — add a utility function check_plan_feature(org, feature_name) in a separate helpers.py.",
                "Subscription records must track: plan_tier, billing_cycle (monthly/annual), current_period_start, current_period_end, stripe_subscription_id.",
            ]

        # Return generic domain-safety rules for unknown verticals
        return [
            f"No domain-specific constraints found for vertical '{vertical}' — apply general data integrity rules.",
            "All unique fields must be unique across all seed records — never repeat a value in a unique column.",
            "All FK references must point to records that are created before the referencing record.",
        ]

    # ── Compliance constraints ────────────────────────────────────────────────

    def get_compliance_constraints(self, compliance_standard: str) -> List[str]:
        """Return HIPAA, PCI-DSS, GDPR, SOC2 compliance rules."""
        standard = (compliance_standard or "").upper().strip()

        if standard == "HIPAA":
            return [
                "Never log Protected Health Information (PHI): patient name, DOB, diagnosis, SSN, address, phone, email, medical record number.",
                "All PHI fields must be encrypted at rest — use application-level encryption or DB column encryption, not just TLS.",
                "Every access to a patient record must write an audit log entry: who accessed it, when, from which IP.",
                "PHI must never be included in error messages, stack traces, or API error responses.",
                "User authentication must enforce MFA for any role that can access PHI.",
                "Data retention: PHI must be retained for at least 6 years — never implement hard-delete on patient records; use soft-delete with is_active flag.",
                "Business Associate Agreements (BAA) must be in place for all third-party services that process PHI — add a comment in the relevant service integration.",
            ]

        if standard == "PCI-DSS":
            return [
                "Never store Primary Account Number (PAN/card number), CVV, or PIN — not even temporarily.",
                "If you must display a card number, mask all but the last 4 digits: **** **** **** 1234.",
                "All payment data transmission must use TLS 1.2 or higher — add a server-side enforcement comment.",
                "Store only the payment_intent_id or token from the payment processor (Stripe, etc.), never raw card data.",
                "Access to payment endpoints must be logged with user ID, timestamp, and action type.",
                "Payment processing code must be isolated in a dedicated module — never mix business logic with payment logic.",
            ]

        if standard == "GDPR":
            return [
                "Every model that stores personal data (name, email, IP, location) must have a data_retention_days field or be covered by a retention policy comment.",
                "Users must be able to request deletion of their personal data — implement a soft-delete pattern with is_deleted flag and deleted_at timestamp.",
                "Consent must be recorded: add a consent_given_at (DateTime) field to User model and never send marketing without it.",
                "Personal data must not be transferred outside the EU without explicit mechanism — add a data_residency comment on storage config.",
                "Data breach notification: log all access to personal data so breach impact can be assessed within 72-hour window.",
                "Right to access: every User must be able to export all their personal data — implement a /users/me/export endpoint.",
            ]

        if standard == "SOC2":
            return [
                "All administrative actions must be logged: who did what, when, from where (IP, user agent).",
                "Authentication events (login, logout, failed login, password change) must be written to an immutable audit log.",
                "All inter-service communication must use mTLS or signed JWT tokens — never unauthenticated service-to-service calls.",
                "Secrets (API keys, DB passwords) must be loaded from environment variables or a secrets manager — never hard-coded.",
                "Automated vulnerability scanning must be part of the CI pipeline — add a comment in Dockerfile referencing the scan step.",
                "Availability SLA must be tracked: add a health check endpoint /health that returns service status and uptime.",
                "Change management: every database migration must be reversible — ensure Alembic downgrade() is implemented.",
            ]

        return [
            f"No specific compliance rules found for standard '{compliance_standard}'.",
            "Apply general security best practices: input validation, output encoding, least-privilege access.",
        ]

    # ── Domain-specific constraint methods ────────────────────────────────────

    def get_hipaa_constraints(self) -> List[str]:
        """Returns HIPAA-specific backend constraints for healthcare apps."""
        return [
            "All PHI fields (dob, ssn, diagnosis, prescription) must have field-level encryption markers",
            "Every model READ operation must write to AuditLog (patient_id, action, accessor_id, timestamp)",
            "No plaintext SSN or date-of-birth in API responses — mask as '***-**-XXXX' or age-only",
            "Bulk export endpoints require superadmin role and HIPAA_EXPORT_APPROVED env flag",
            "All authentication attempts logged with IP and outcome",
        ]

    def get_pci_constraints(self) -> List[str]:
        """Returns PCI-DSS specific constraints for fintech apps."""
        return [
            "Never log or return full card numbers — store only last 4 digits",
            "All payment amounts stored as numeric(10,2) — never float arithmetic on currency",
            "Stripe token references only — no raw card data in database",
            "Every financial transaction creates an immutable AuditLog record",
            "API responses must never include raw payment instrument identifiers",
        ]

    def get_domain_constraints(self, domain: str) -> List[str]:
        """Returns all domain-specific constraints for a given app domain."""
        domain_lower = domain.lower()
        if any(w in domain_lower for w in ["health", "medical", "clinic", "hospital", "patient"]):
            return self.get_hipaa_constraints()
        if any(w in domain_lower for w in ["finance", "fintech", "payment", "bank", "invoice", "wallet"]):
            return self.get_pci_constraints()
        return []

    # ── Prompt formatting ─────────────────────────────────────────────────────

    def format_for_prompt(self, constraints: List[str]) -> str:
        """Format a constraint list as a numbered block for LLM prompt injection."""
        if not constraints:
            return ""
        lines = ["HARD CONSTRAINTS (you must follow every rule below):"]
        for i, rule in enumerate(constraints, start=1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)
