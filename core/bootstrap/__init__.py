"""
Aether-One Bootstrap & Runtime Manager

This module provides the authoritative system initialization, lifecycle management,
and runtime control for Aether-One.

CRITICAL RESPONSIBILITIES:
- Detect and validate system environment (OS, CPU, RAM, disk)
- Enforce OFFLINE-FIRST guarantees (no network access)
- Load and validate system policies
- Initialize memory and state systems
- Start agents in strict deterministic order
- Monitor runtime health
- Manage power levels (minimal → full)
- Enter safe-mode on violations
- Provide recovery and factory reset

OFFLINE GUARANTEES:
- Refuses to start if network guardrails cannot be enforced
- All operations are local-only
- No telemetry, no cloud APIs, no silent networking
"""

from .runtime_manager import RuntimeManager, RuntimeState, PowerLevel, RuntimeConfig, RuntimeStatus
from .environment_detector import EnvironmentInfo, detect_environment
from .offline_guard import OfflineGuard, NetworkViolationError
from .safe_mode import SafeMode, SafeModeReason

__all__ = [
    "RuntimeManager",
    "RuntimeState",
    "PowerLevel",
    "RuntimeConfig",
    "RuntimeStatus",
    "EnvironmentInfo",
    "detect_environment",
    "OfflineGuard",
    "NetworkViolationError",
    "SafeMode",
    "SafeModeReason",
]
