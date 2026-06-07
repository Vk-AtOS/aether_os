"""
AetherOS — Unified Error Types
Merged from aether2/aether/core/errors.py (primary) with AetherOS extensions.
"""
from __future__ import annotations
import logging
from enum import Enum
from typing import Optional, Any

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SNAPSHOT = "snapshot"
    ROLLBACK = "rollback"
    MODIFY_CODE = "modify_code"
    DELETE = "delete"
    NETWORK = "network"
    APPROVE = "approve"
    ADMIN = "admin"


class SystemState(str, Enum):
    BOOTING = "booting"
    IDLE = "idle"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


class AetherError(RuntimeError):
    """Base error for all AetherOS exceptions. Always carries structured details."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.details = details
        logger.debug("AetherError raised: %s | details=%s", message, details)


class InvariantViolation(AetherError):
    """A system invariant was violated — this should never happen in normal operation."""


class PermissionDenied(AetherError):
    """The actor lacks the required permission for this action."""


class ApprovalRequired(AetherError):
    """Action requires explicit human approval before proceeding."""


class DeliveryFailure(AetherError):
    """A delivery pipeline stage failed (notification, webhook, etc.)."""


class SandboxViolation(AetherError):
    """Code executed outside allowed sandbox boundaries."""


class LLMUnavailable(AetherError):
    """Neither primary (Anthropic) nor fallback (Ollama) LLM is reachable."""


class SnapshotError(AetherError):
    """Snapshot creation, restore, or integrity check failed."""


class PolicyViolation(AetherError):
    """A policy rule was violated."""


class ConfigurationError(AetherError):
    """Required configuration or environment variable is missing."""


class PipelineError(AetherError):
    """Pipeline execution error (phase failure, max retries, etc.)."""


class PipelineBlockedError(PipelineError):
    """A critical phase failure has blocked the pipeline from continuing."""


class LLMCallError(AetherError):
    """A structured LLM call failed after all retries."""


class GateFailure(AetherError):
    """Phase gate validation failed and could not be recovered."""


class ZeroTrustViolation(AetherError):
    """Zero-trust execution ticket is missing, invalid, or expired."""
