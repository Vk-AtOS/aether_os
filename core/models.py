from __future__ import annotations
import uuid
import time
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, ForeignKey, Float, Boolean, Text, DateTime, JSON, Integer, Index, UniqueConstraint, false, func
from sqlalchemy import event
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship
from .db import Base
from .encryption import EncryptedText

# PostgreSQL columns are TIMESTAMP WITHOUT TIME ZONE — use naive UTC datetimes.
def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=lambda: f"org_{uuid.uuid4()}")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial")  # trial, pro, enterprise
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    trial_runs_used: Mapped[int] = mapped_column(default=0)
    trial_runs_limit: Mapped[int] = mapped_column(default=3)
    storage_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    autonomous_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    data_region: Mapped[str] = mapped_column(String(20), default="global")
    scim_token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # DB-H1: bcrypt hash; plaintext only returned at generation time
    # sha256 of the SCIM token (a 256-bit random value, so a plain digest is enough): lets a request find its org
    # with one indexed lookup instead of bcrypt-checking every org that has a token.
    scim_token_lookup: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Unix time the paid period ends (core.billing.payments). NULL = no period on record
    # (trial/free, or a plan not bought through a one-off payment).
    plan_period_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())  # M7: change tracking
    # LLM spend control (KAN-116): per-org USD cap overriding the plan default, and an org-level kill switch.
    llm_monthly_cap_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Cap the ORG ADMIN chose for itself (lowers only). Kept apart from llm_monthly_cap_usd so a tenant can never
    # undo a cap the platform set: effective cap = min(platform-or-plan cap, org cap).
    llm_org_cap_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Admin MFA policy (KAN-186): when on, owners/admins without MFA are locked to MFA enrolment
    # once the grace period (unix time, NULL = none) has passed.
    require_admin_mfa: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    admin_mfa_grace_until: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    users: Mapped[List["User"]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    api_keys: Mapped[List["APIKey"]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    runs: Mapped[List["Run"]] = relationship(back_populates="organisation")

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), ForeignKey("organisations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member")  # owner, member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user_preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    mfa_secret: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)  # SEC-H1/FIX15: set on admin password reset
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())  # M7: change tracking
    # The Velaris employee record this sign-in IS (own leave, payslips, policies). Set by an org admin only; one
    # employee record per sign-in per organisation (uq_users_org_velaris_employee).
    velaris_employee_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    organisation: Mapped["Organisation"] = relationship(back_populates="users")
    __table_args__ = (Index("uq_users_org_velaris_employee", "org_id", "velaris_employee_id", unique=True),)

class PasswordHistory(Base):
    """Hashes of a user's previous passwords, so a change or reset cannot go back to a recent one."""
    __tablename__ = "password_history"
    __table_args__ = (Index("ix_password_history_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), ForeignKey("organisations.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(String(100), nullable=False, default="read,write", server_default="read,write")  # comma list of read|write
    last_used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    organisation: Mapped["Organisation"] = relationship(back_populates="api_keys")

class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), ForeignKey("organisations.id"), nullable=True, index=True)
    command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    live_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    run_version: Mapped[int] = mapped_column(default=1)
    parallel_run_group_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    self_test_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Pipeline input/output fields
    raw_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="general")
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    current_phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phases: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    council_preflight: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    council_delivery: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    parent_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    branch_phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    quality_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    organisation: Mapped[Optional["Organisation"]] = relationship(back_populates="runs")
    events: Mapped[List["Event"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    snapshots: Mapped[List["Snapshot"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    phase_completions: Mapped[List["PhaseCompletion"]] = relationship(back_populates="run", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")

class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="snapshots")

class PhaseCompletion(Base):
    __tablename__ = "phase_completions"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="phase_completions")

class PhaseConfig(Base):
    __tablename__ = "phase_configs"

    org_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[int] = mapped_column(default=1)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class RunMetadata(Base):
    __tablename__ = "run_metadata"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    what: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    alternatives: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    human_choice: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(default=300)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # The org-wide pending-decisions inbox filters by org and status, newest first.
    __table_args__ = (Index("ix_decisions_org_status_created", "org_id", "status", "created_at"),)

class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    events: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # the HMAC signing key, Fernet-encrypted (core.encryption); never plaintext
    secret_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # M3: bcrypt hash; plaintext only returned at creation time
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)

class OrgApiKey(Base):
    """Per-org LLM provider API key storage (replaces shared .env approach)."""
    __tablename__ = "org_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)   # "anthropic", "google", "openrouter", "bedrock"
    api_key: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)   # user_id who saved it

    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_org_provider"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # M4: index for compliance queries
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    log_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

class SamlConfig(Base):
    __tablename__ = "saml_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False)
    idp_entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    idp_sso_url: Mapped[str] = mapped_column(String(512), nullable=False)
    idp_cert: Mapped[Text] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # M5: enforce one SAML config per org at the DB level
    __table_args__ = (UniqueConstraint('org_id', name='uq_saml_config_org_id'),)

try:
    from pgvector.sqlalchemy import Vector as _PgVector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False

class ArtifactEmbedding(Base):
    __tablename__ = "artifact_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # JSON fallback
    if _HAS_PGVECTOR:
        embedding_vector = mapped_column(_PgVector(1536), nullable=True)  # pgvector native column
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

class MarketplaceProfile(Base):
    __tablename__ = "marketplace_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    profile_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

class GlobalPattern(Base):
    __tablename__ = "global_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[Optional[str]] = mapped_column(String(50), ForeignKey("organisations.id"), nullable=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(100), nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(default=0)
    avg_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── LLM Cache (replaces ~/.aether_os/llm_cache.db) ───────────────────────────

class LLMCacheEntry(Base):
    """Shared LLM response cache — replaces per-process SQLite file."""
    __tablename__ = "llm_cache_entries"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 hex
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    hit_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_hit_at: Mapped[float] = mapped_column(Float, default=time.time)


# ── Token Budget (replaces ~/.aether_os/token_budget.db) ─────────────────────

class TokenBudgetRecord(Base):
    """Per-org monthly token usage — replaces per-process SQLite file."""
    __tablename__ = "token_budget_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)       # "YYYY-MM"
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    runs: Mapped[int] = mapped_column(default=0)
    cache_hits: Mapped[int] = mapped_column(default=0)
    cache_misses: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint("org_id", "month", name="uq_token_budget_org_month"),)


# ── Plugin Registry (replaces ~/.aether_os/plugins.db) ───────────────────────

class LLMCallRecord(Base):
    """Individual LLM call record for cost/usage tracking (replaces billing.db)."""
    __tablename__ = "llm_call_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class InstalledPluginRecord(Base):
    """Installed plugins per org — replaces per-process SQLite file."""
    __tablename__ = "installed_plugins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    plugin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # encrypted JSON
    installed_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_tested_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    test_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # ok | fail
    __table_args__ = (UniqueConstraint("org_id", "plugin_id", name="uq_installed_plugin_org_plugin"),)



class LlmConfig(Base):
    """Per-org (or global) LLM provider configuration persisted in DB."""
    __tablename__ = "llm_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openrouter")
    heavy_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    light_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    prefer_paid: Mapped[bool] = mapped_column(default=False)
    council_enabled: Mapped[bool] = mapped_column(default=True)
    council_strict_mode: Mapped[bool] = mapped_column(default=False)
    # LangSmith
    langsmith_enabled: Mapped[bool] = mapped_column(default=False)
    langsmith_project: Mapped[str] = mapped_column(String(255), default="aetheros-factory")
    # Bedrock
    bedrock_enabled: Mapped[bool] = mapped_column(default=False)
    bedrock_region: Mapped[str] = mapped_column(String(50), default="us-east-1")
    bedrock_model_heavy: Mapped[str] = mapped_column(String(255), default="us.anthropic.claude-sonnet-4-6")
    bedrock_model_light: Mapped[str] = mapped_column(String(255), default="us.anthropic.claude-haiku-4-5-20251001-v1:0")

    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=time.time)


class RunSpec(Base):
    """Stores frontend/backend spec JSON attached to a run (from Builder tabs)."""
    __tablename__ = "run_specs"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    spec_type: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'frontend' | 'backend'
    spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Notification(Base):
    """In-app notification for org members."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)  # None = org-wide
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class NotificationPref(Base):
    """Which notification events reach whom, per channel. user_id '' is the organisation default; a user's
    row overrides it. No row = the built-in default (everything on), so existing behaviour is unchanged."""
    __tablename__ = "notification_prefs"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "event_type", name="uq_notification_prefs"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=True)


class CodebaseProfile(Base):
    """Imported codebase profile for use as additional context in pipeline runs."""
    __tablename__ = "codebase_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), ForeignKey("organisations.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(256), nullable=False)
    detected_stack: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"backend": "FastAPI", "frontend": "React", "db": "PostgreSQL"}
    file_tree: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"dirs": [...], "key_files": [...]}
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # one-paragraph description
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BuildFeedback(Base):
    """User star-rating and tag feedback on a completed pipeline run."""
    __tablename__ = "build_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # e.g. ["great-ui", "fast-api", "clean-models"]
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # one rating per user per run (NULL user ids stay unconstrained: SQL NULLs are distinct)
    __table_args__ = (UniqueConstraint("run_id", "user_id", name="uq_build_feedback_run_user"),)


class GoldenBuild(Base):
    """Curated best-in-class build examples used as few-shot context for LLM prompts."""
    __tablename__ = "golden_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # first 500 chars of original prompt
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # auto-scored 0-100
    user_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # avg of BuildFeedback.rating
    p04_sample: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # excerpt of generated models.py
    p05_sample: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # excerpt of generated Dashboard.tsx
    entity_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    domain_ir_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # entity names + fields summary
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("run_id", name="uq_golden_build_run"),)


class PipelineEvent(Base):
    """Persistent record of every pipeline event (Fix 24)."""
    __tablename__ = "pipeline_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class LLMTrace(Base):
    """Deep observability trace for every LLM call attempt."""
    __tablename__ = "llm_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    phase: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    task_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class QuestionnaireSession(Base):
    """Interactive phase-by-phase questionnaire session for guided pipeline mode."""
    __tablename__ = "questionnaire_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # denormalised from runs.org_id (set on insert)
    stage_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|sent|completed|expired
    access_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)  # sha256 of the share token, never the token
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    respondent_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    respondent_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agency_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agency_logo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    answers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── org_id of the run-owned tables ────────────────────────────────────────────
# These rows belong to a run, and the run to an organisation. org_id is repeated on them so that
# per-organisation queries, retention and row-level security do not need a join. Every write path
# goes through the ORM, so the column is filled once, here, from the run (one lookup per run and
# flush, the run is usually in the identity map already) instead of in each of the ~15 writers.
_RUN_OWNED = (Event, Snapshot, PhaseCompletion, RunMetadata, RunSpec, PipelineEvent, LLMTrace, QuestionnaireSession)


@event.listens_for(Session, "before_flush")
def _fill_org_id_from_run(session: Session, flush_context, instances) -> None:
    pending = [o for o in session.new if isinstance(o, _RUN_OWNED) and o.org_id is None and o.run_id]
    if not pending:
        return
    orgs: dict = {}
    with session.no_autoflush:
        for obj in pending:
            if obj.run_id not in orgs:
                run = session.get(Run, obj.run_id)
                orgs[obj.run_id] = run.org_id if run is not None else None
            obj.org_id = orgs[obj.run_id]


from . import scim_models  # noqa: E402,F401  registers scim_groups / scim_group_members with Base

from . import models_ops  # noqa: E402,F401  (registers webhook_outbox / notification_quiet_hours on Base.metadata)

from .models_learning import LearningClarificationPending, UserLearningPattern  # noqa: E402,F401  (split out: line limit)

from .models_memory import FixMemory, RunPatternMemory  # noqa: E402,F401  (KAN-215 run memory; split out: line limit)
