from __future__ import annotations
import uuid
import time
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, ForeignKey, Float, Boolean, Text, DateTime, JSON, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base
from .encryption import EncryptedText

class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial")  # trial, pro, enterprise
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    trial_runs_used: Mapped[int] = mapped_column(default=0)
    trial_runs_limit: Mapped[int] = mapped_column(default=3)
    storage_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    autonomous_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    data_region: Mapped[str] = mapped_column(String(20), default="global")
    scim_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    users: Mapped[List["User"]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    api_keys: Mapped[List["APIKey"]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    runs: Mapped[List["Run"]] = relationship(back_populates="organisation")

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member")  # owner, member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user_preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    mfa_secret: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    organisation: Mapped["Organisation"] = relationship(back_populates="users")

class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    organisation: Mapped["Organisation"] = relationship(back_populates="api_keys")

class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organisations.id"), nullable=True, index=True)
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
    agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")

class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="snapshots")

class PhaseCompletion(Base):
    __tablename__ = "phase_completions"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), primary_key=True)
    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="phase_completions")

class PhaseConfig(Base):
    __tablename__ = "phase_configs"

    org_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[int] = mapped_column(default=1)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class RunMetadata(Base):
    __tablename__ = "run_metadata"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    events: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)

class OrgApiKey(Base):
    """Per-org LLM provider API key storage (replaces shared .env approach)."""
    __tablename__ = "org_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)   # "anthropic", "google", "openrouter", "bedrock"
    api_key: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)   # user_id who saved it

    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_org_provider"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    log_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

class SamlConfig(Base):
    __tablename__ = "saml_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idp_entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    idp_sso_url: Mapped[str] = mapped_column(String(512), nullable=False)
    idp_cert: Mapped[Text] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class ArtifactEmbedding(Base):
    __tablename__ = "artifact_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class MarketplaceProfile(Base):
    __tablename__ = "marketplace_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    profile_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class GlobalPattern(Base):
    __tablename__ = "global_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(100), nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(default=0)
    avg_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)       # "YYYY-MM"
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    runs: Mapped[int] = mapped_column(default=0)
    cache_hits: Mapped[int] = mapped_column(default=0)
    cache_misses: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


# ── Plugin Registry (replaces ~/.aether_os/plugins.db) ───────────────────────

class LLMCallRecord(Base):
    """Individual LLM call record for cost/usage tracking (replaces billing.db)."""
    __tablename__ = "llm_call_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
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
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    plugin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # encrypted JSON
    installed_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_tested_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    test_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # ok | fail


class LlmConfig(Base):
    """Per-org (or global) LLM provider configuration persisted in DB."""
    __tablename__ = "llm_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openrouter")
    heavy_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    light_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    prefer_paid: Mapped[bool] = mapped_column(default=False)
    council_enabled: Mapped[bool] = mapped_column(default=True)
    council_strict_mode: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=time.time)


class UserLearningPattern(Base):
    """Per-user isolated learning patterns. Every query MUST filter by org_id AND user_id."""
    __tablename__ = "user_learning_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pattern_key: Mapped[str] = mapped_column(String(256), nullable=False)
    pattern_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    occurrence_count: Mapped[int] = mapped_column(default=1)
    source_run_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array of run IDs
    last_updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class LearningClarificationPending(Base):
    """Project-scoped clarification questions pending user answer."""
    __tablename__ = "learning_clarifications_pending"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False, default="clarification")
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    answer: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RunSpec(Base):
    """Stores frontend/backend spec JSON attached to a run (from Builder tabs)."""
    __tablename__ = "run_specs"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    spec_type: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'frontend' | 'backend'
    spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Notification(Base):
    """In-app notification for org members."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)  # None = org-wide
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class CodebaseProfile(Base):
    """Imported codebase profile for use as additional context in pipeline runs."""
    __tablename__ = "codebase_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(256), nullable=False)
    detected_stack: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"backend": "FastAPI", "frontend": "React", "db": "PostgreSQL"}
    file_tree: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"dirs": [...], "key_files": [...]}
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # one-paragraph description
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
