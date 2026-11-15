"""
AetherOS — Core Module Tests
Tests: errors, config, db, memory store
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

# Ensure aether_os is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── Error types ───────────────────────────────────────────────────────────────

def test_error_hierarchy():
    from aether_os.core.errors import (
        AetherError, InvariantViolation, PermissionDenied,
        SandboxViolation, LLMUnavailable, PolicyViolation
    )
    for cls in (InvariantViolation, PermissionDenied, SandboxViolation, LLMUnavailable, PolicyViolation):
        assert issubclass(cls, AetherError)
        assert issubclass(cls, RuntimeError)


def test_error_carries_details():
    from aether_os.core.errors import AetherError
    err = AetherError("test message", details={"key": "value"})
    assert str(err) == "test message"
    assert err.details == {"key": "value"}


def test_permission_enum():
    from aether_os.core.errors import Permission
    assert Permission.READ == "read"
    assert Permission.ADMIN == "admin"


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_defaults():
    from aether_os.core.config.loader import AetherConfig
    cfg = AetherConfig(config_path="/nonexistent/path.yaml")
    assert cfg.get("models.primary") == "claude-sonnet-4-6"
    assert cfg.get("llm.anthropic_model") == "claude-sonnet-4-6"
    assert cfg.get("pipeline.max_retries") == 3


def test_config_get_nested():
    from aether_os.core.config.loader import AetherConfig
    cfg = AetherConfig(config_path="/nonexistent/path.yaml")
    assert cfg.get("pipeline.stage_timeout_seconds.requirements") == 120


def test_config_get_missing_returns_default():
    from aether_os.core.config.loader import AetherConfig
    cfg = AetherConfig(config_path="/nonexistent/path.yaml")
    assert cfg.get("nonexistent.key", "fallback") == "fallback"


def test_config_set_runtime():
    from aether_os.core.config.loader import AetherConfig
    cfg = AetherConfig(config_path="/nonexistent/path.yaml")
    cfg.set("custom.key", "custom_value")
    assert cfg.get("custom.key") == "custom_value"


def test_config_require_missing_raises():
    from aether_os.core.config.loader import AetherConfig
    from aether_os.core.errors import ConfigurationError
    cfg = AetherConfig(config_path="/nonexistent/path.yaml")
    with pytest.raises(ConfigurationError):
        cfg.require("definitely.not.there")


def test_config_yaml_overlay(tmp_path):
    import yaml
    from aether_os.core.config.loader import AetherConfig
    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml.dump({"pipeline": {"max_retries": 10}}))
    cfg = AetherConfig(config_path=str(config_file))
    assert cfg.get("pipeline.max_retries") == 10
    # Default not overridden
    assert cfg.get("models.primary") == "claude-sonnet-4-6"


# ── DB ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_engine_created(tmp_path):
    import os
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    # Reset singleton
    import aether_os.core.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None

    engine = db_mod.get_engine()
    assert engine is not None

    await db_mod.close_db()
    db_mod._engine = None
    db_mod._session_factory = None
    del os.environ["DATABASE_URL"]


# ── Audit logger ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_logger_log(tmp_path):
    from aether_os.core.audit.logger import AuditLogger
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(storage_path=log_path)

    entry = await logger.log("test_actor", "test_action", {"key": "val"}, "session1")

    assert entry["actor"] == "test_actor"
    assert entry["action"] == "test_action"
    assert "id" in entry
    assert log_path.exists()
    assert logger.count() == 1


def test_audit_logger_sync(tmp_path):
    from aether_os.core.audit.logger import AuditLogger
    log_path = tmp_path / "audit_sync.jsonl"
    logger = AuditLogger(storage_path=log_path)
    entry = logger.log_sync("actor", "action", {"data": 1})
    assert entry["actor"] == "actor"
    assert logger.count() == 1


def test_audit_logger_filter(tmp_path):
    from aether_os.core.audit.logger import AuditLogger
    logger = AuditLogger()
    logger.log_sync("alice", "create", {})
    logger.log_sync("bob", "delete", {})
    logger.log_sync("alice", "update", {})

    alice_entries = logger.filter(actor="alice")
    assert len(alice_entries) == 2
    delete_entries = logger.filter(action="delete")
    assert len(delete_entries) == 1


# ── Decision Ledger ───────────────────────────────────────────────────────────

def test_ledger_save_and_retrieve(tmp_path):
    import asyncio
    import os
    import aether_os.core.db as _db_mod

    old_db = os.environ.get("DATABASE_URL")
    _db_mod._engine = None
    _db_mod._session_factory = None
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/ledger_test.db"
    try:
        from aether_os.core.db import init_db, get_session_factory
        from aether_os.core.models import Organisation
        asyncio.run(init_db())

        async def _create_org():
            sf = get_session_factory()
            async with sf() as session:
                session.add(Organisation(id="test-org", name="Test", slug="test-ledger"))
                await session.commit()

        asyncio.run(_create_org())

        from aether_os.core.audit.ledger import DecisionLedger
        ledger = DecisionLedger()
        ledger.save_run("run-001", "test command", org_id="test-org", status="running")
        ledger.log_event("run-001", "agent_x", "start", "beginning")
        ledger.update_run_status("run-001", "completed")

        history = ledger.get_run_history("test-org")
        # get_run_history returns {"items": [...], "total": N} — extract the list
        items = history["items"] if isinstance(history, dict) else history
        assert len(items) >= 1
        assert items[0]["id"] == "run-001"
        assert items[0]["status"] == "completed"

        detail = ledger.get_run_detail("run-001")
        assert detail["id"] == "run-001"
        assert len(detail["events"]) >= 1
    finally:
        # Reset all shared singletons so subsequent tests start clean
        _db_mod._engine = None
        _db_mod._session_factory = None
        from aether_os.core.audit.ledger import DecisionLedger
        DecisionLedger._instance = None
        if old_db is not None:
            os.environ["DATABASE_URL"] = old_db
        else:
            os.environ.pop("DATABASE_URL", None)


def test_ledger_not_found_returns_empty(tmp_path):
    import asyncio
    import os
    import aether_os.core.db as _db_mod

    old_db = os.environ.get("DATABASE_URL")
    _db_mod._engine = None
    _db_mod._session_factory = None
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/ledger_test2.db"
    try:
        from aether_os.core.db import init_db
        asyncio.run(init_db())
        from aether_os.core.audit.ledger import DecisionLedger
        ledger = DecisionLedger()
        result = ledger.get_run_detail("nonexistent-run")
        assert result == {}
    finally:
        _db_mod._engine = None
        _db_mod._session_factory = None
        if old_db is not None:
            os.environ["DATABASE_URL"] = old_db
        else:
            os.environ.pop("DATABASE_URL", None)


# ── Memory Store ──────────────────────────────────────────────────────────────

def test_memory_store_round_trip(tmp_path):
    from aether_os.core.memory.store import MemoryStore, MemoryRecord
    store = MemoryStore(db_path=str(tmp_path / "memory.db"))

    record = MemoryRecord(
        input_hash="abc123",
        input_text="Build a REST API",
        output_text="from fastapi import FastAPI...",
        task_type="code_generation",
    )
    store.store_sync(record)

    results = store.retrieve_sync("abc123", k=5)
    assert len(results) >= 1
    assert results[0].input_hash == "abc123"
    assert results[0].task_type == "code_generation"


def test_memory_store_increments_success_count(tmp_path):
    from aether_os.core.memory.store import MemoryStore, MemoryRecord
    store = MemoryStore(db_path=str(tmp_path / "memory2.db"))

    for _ in range(3):
        store.store_sync(MemoryRecord(
            input_hash="hash1",
            input_text="same input",
            output_text="same output",
            task_type="code_generation",
        ))

    results = store.retrieve_sync("hash1")
    assert results[0].success_count == 3


def test_memory_store_stats(tmp_path):
    from aether_os.core.memory.store import MemoryStore, MemoryRecord
    store = MemoryStore(db_path=str(tmp_path / "memory3.db"))
    store.store_sync(MemoryRecord(input_hash="h1", task_type="code_generation"))
    store.store_sync(MemoryRecord(input_hash="h2", task_type="security_scan"))
    stats = store.stats()
    assert stats["total_records"] == 2


# ── Policy Engine ─────────────────────────────────────────────────────────────

def test_policy_default():
    from aether_os.core.policy.engine import default_policy
    policy = default_policy()
    assert policy.strict_mode is True
    assert policy.org_profile == "DEFAULT"


def test_policy_blocked_operation():
    from aether_os.core.policy.engine import default_policy, evaluate_operation
    policy = default_policy()
    decision = evaluate_operation(policy, "exec_shell_untrusted", "LOW", is_guarded=True)
    assert decision.allowed is False
    assert "Blocked" in decision.reason


def test_policy_requires_approval_for_high_risk():
    from aether_os.core.policy.engine import default_policy, evaluate_operation
    policy = default_policy()
    # Default max_risk_without_approval = LOW, so HIGH requires approval
    decision = evaluate_operation(policy, "deploy_to_prod", "HIGH", is_guarded=True)
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_policy_low_risk_auto_approved():
    from aether_os.core.policy.engine import default_policy, evaluate_operation
    policy = default_policy()
    policy.strict_mode = False  # Allow unguarded for this test
    decision = evaluate_operation(policy, "read_file", "LOW", is_guarded=False)
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_policy_fintech_preset():
    from aether_os.core.policy.engine import preset_policy
    policy = preset_policy("FINTECH")
    assert policy.org_profile == "FINTECH"
    assert "modify_payment_logic" in policy.blocked_operations


# ── Fingerprinter ─────────────────────────────────────────────────────────────

def test_fingerprinter_stable():
    from aether_os.core.memory.fingerprinter import fingerprint
    log1 = "Error: NameError: name 'foo' is not defined at line 42"
    log2 = "Error: NameError: name 'foo' is not defined at line 42"
    assert fingerprint(log1) == fingerprint(log2)


def test_fingerprinter_normalises_addresses():
    from aether_os.core.memory.fingerprinter import fingerprint
    log1 = "Error at 0x7f1234ab"
    log2 = "Error at 0x7f9999ff"
    assert fingerprint(log1) == fingerprint(log2)


# ── State Machine ─────────────────────────────────────────────────────────────

def test_state_machine_transitions():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
    sm = PipelineStateMachine(run_id="test-001")
    assert sm.current_state == PipelineState.IDLE

    sm.transition_to(PipelineState.REQUIREMENTS, reason="start")
    assert sm.current_state == PipelineState.REQUIREMENTS

    sm.transition_to(PipelineState.ARCHITECTURE, reason="done")
    assert sm.current_state == PipelineState.ARCHITECTURE


def test_state_machine_invalid_transition_raises():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState, StateTransitionError
    sm = PipelineStateMachine(run_id="test-002")
    with pytest.raises(StateTransitionError):
        sm.transition_to(PipelineState.COMPLETE)  # Can't jump from IDLE to COMPLETE


def test_state_machine_next_phase():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
    sm = PipelineStateMachine(run_id="test-003")
    sm.transition_to(PipelineState.REQUIREMENTS)
    sm.transition_to(PipelineState.ARCHITECTURE)
    next_p = sm.next_phase()
    assert next_p == PipelineState.SCAFFOLDING


def test_state_machine_terminal_states():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
    sm = PipelineStateMachine(run_id="test-004")
    sm.transition_to(PipelineState.REQUIREMENTS)
    sm.transition_to(PipelineState.FAILED)
    assert sm.is_terminal()
