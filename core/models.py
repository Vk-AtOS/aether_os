from __future__ import annotations
import uuid
import time
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, ForeignKey, Float, Boolean, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial")  # trial, pro, enterprise
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    trial_runs_used: Mapped[int] = mapped_column(default=0)
    trial_runs_limit: Mapped[int] = mapped_column(default=3)
    storage_used_mb: Mapped[float] = mapped_column(Float, default=0.0)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organisation: Mapped["Organisation"] = relationship(back_populates="users")

class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organisation: Mapped["Organisation"] = relationship(back_populates="api_keys")

class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organisations.id"), nullable=True)
    command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    live_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_version: Mapped[int] = mapped_column(default=1)

    organisation: Mapped[Optional["Organisation"]] = relationship(back_populates="runs")
    events: Mapped[List["Event"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    snapshots: Mapped[List["Snapshot"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    phase_completions: Mapped[List["PhaseCompletion"]] = relationship(back_populates="run", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")

class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="snapshots")

class PhaseCompletion(Base):
    __tablename__ = "phase_completions"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), primary_key=True)
    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="phase_completions")

class PhaseConfig(Base):
    __tablename__ = "phase_configs"

    phase_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[int] = mapped_column(default=1)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class RunMetadata(Base):
    __tablename__ = "run_metadata"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    priority: Mapped[str] = mapped_column(String(50), default="normal")
    updated_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
