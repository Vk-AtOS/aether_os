"""
PostgreSQL SQLAlchemy models for DCSP.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True,
        nullable=False)
    plan = Column(String(20), default="free")
        # free, pro, enterprise
    created_at = Column(DateTime,
        default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class RepairJob(Base):
    """Tracks a single repair job attempt from a CI failure."""

    __tablename__ = "repair_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36),
        ForeignKey("tenants.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    repo_name = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=False)
    commit_sha = Column(String(255), nullable=True)
    ci_system = Column(String(255), nullable=True)
    detected_language = Column(String(255), nullable=True)
    success = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    escalated = Column(Boolean, default=False)
    explanation = Column(Text, nullable=False)
    patch_diff = Column(Text, nullable=True)
    slm_generated = Column(Boolean, default=False)
    source = Column(String(20), default="slm", nullable=True)
    fingerprint = Column(String(32), nullable=True)
    approved = Column(Boolean, nullable=True)  # None=pending, True=approved, False=rejected
    approved_pr_url = Column(String(500), nullable=True)
    violations = Column(Text, nullable=True)  # JSON-serialized list
    patch_edited = Column(Boolean, default=False)
    sandbox_result = Column(String(20), nullable=True)
    # "passed", "failed", "skipped", None


class FailureFingerprint(Base):
    """Historical failure fingerprints and their associated patches."""

    __tablename__ = "failure_fingerprints"

    id = Column(Integer, primary_key=True)
    fingerprint_hash = Column(String(64), unique=True, index=True)
    error_type = Column(String(255))
    stack_trace_pattern = Column(Text)
    failing_test = Column(Text)
    target_module = Column(String(511))
    patch_diff = Column(Text, nullable=False)
    success_rate = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Audit log for security and compliance events."""
    __tablename__ = "audit_logs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36),
        ForeignKey("tenants.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    action = Column(String(100))
    actor = Column(String(100))
    job_id = Column(String(36), nullable=True)
    repo_name = Column(String(200), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36),
        ForeignKey("tenants.id"),
        nullable=False)
    name = Column(String(200), nullable=False)
    key_hash = Column(String(64),
        nullable=False, unique=True)
    key_prefix = Column(String(8),
        nullable=False)
    created_at = Column(DateTime,
        default=datetime.utcnow)
    last_used_at = Column(DateTime,
        nullable=True)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime,
        nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()))
    fingerprint = Column(
        String(255), nullable=False,
        index=True)
    error_type = Column(
        String(100), nullable=True)
    language = Column(
        String(50), nullable=True)
    first_seen = Column(
        DateTime,
        default=datetime.utcnow)
    last_seen = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow)
    affected_repos = Column(
        Text, nullable=True)
    # JSON list of repo names
    job_count = Column(
        Integer, default=1)
    status = Column(
        String(20), default="active")
    # "active", "resolved", "escalated"
    resolution = Column(
        Text, nullable=True)


class StageTiming(Base):
    __tablename__ = "stage_timings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("repair_jobs.id"), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True)
    stage_name = Column(String(100), nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    outcome = Column(String(20), nullable=False)  # success, failure
    timestamp = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """Application users with bcrypt-hashed passwords."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="member")  # admin, member
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    display_name = Column(String(200), nullable=True)


class TenantSettings(Base):
    """Per-tenant configuration settings."""

    __tablename__ = "tenant_settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, unique=True)
    slack_webhook_url = Column(String(500), nullable=True)
    notification_email = Column(String(255), nullable=True)
    github_client_id = Column(String(100), nullable=True)
    github_client_secret = Column(String(100), nullable=True)
    auto_approve_threshold = Column(Float, default=0.95)
    updated_at = Column(DateTime, default=datetime.utcnow)


class GitHubInstallation(Base):
    """Tracks GitHub App installations so DCSP can act on behalf of each account."""

    __tablename__ = "github_installations"

    id = Column(Integer, primary_key=True)
    installation_id = Column(Integer, unique=True, nullable=False, index=True)
    account_login = Column(String(200), nullable=False)
    account_type = Column(String(20), nullable=False)  # "Organization" or "User"
    tenant_id = Column(String(36), nullable=True)       # linked DCSP tenant
    installed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class FederationPattern(Base):
    """Anonymized repair patterns shared via the federation registry.

    Replaces the in-memory _PATTERNS dict so data survives restarts.
    """

    __tablename__ = "federation_patterns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # anonymized fingerprint submitted by a node
    fingerprint = Column(String(255), nullable=False, unique=True, index=True)
    error_type = Column(String(100), nullable=False)
    language = Column(String(50), nullable=False)
    patch_template = Column(Text, nullable=False)
    log_snippet = Column(Text, nullable=True)
    success_count = Column(Integer, default=1)
    confidence = Column(Float, default=0.55)
    # short opaque hash identifying the contributing node
    source_hash = Column(String(16), nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
