"""
AetherOS — Policy Engine Core (migrated from Aether-one)

Original docstring:
Aether-One Policy Engine Core

Enterprise-grade, deterministic policy engine for:

- Strict mode control (disable all unguarded operations).
- Organization-level presets (e.g. DEFAULT, FINTECH, HEALTHCARE).
- Deciding whether an operation:
    - is allowed directly,
    - must go through approval,
    - or is blocked.

Persistence:
- Policy configuration is stored as JSON in the project root, by default:
    .aetherone_policy.json

This module is:
- Pure Python, offline, deterministic.
- Safe to call from API, CLI, or agents.
- The single source of truth about what is allowed in a given project.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants & types
# ---------------------------------------------------------------------------

# Risk levels are ordered from least to most severe.
RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]


def _normalize_risk(level: str) -> str:
    level = (level or "").strip().upper()
    return level if level in RISK_LEVELS else "HIGH"


@dataclass
class PolicyConfig:
    """
    Top-level policy configuration for a project.

    Attributes:
        strict_mode:
            If True, all unguarded / direct execution operations are blocked.
            Only guarded operations (subject to approval) are allowed.

        org_profile:
            Optional organization profile string, e.g. "DEFAULT", "FINTECH",
            "HEALTHCARE". This can drive different defaults.

        max_risk_without_approval:
            Highest risk level that may proceed without explicit approval.
            One of "LOW", "MEDIUM", "HIGH".
            Example:
                - "LOW": anything MEDIUM or HIGH requires approval.
                - "MEDIUM": only HIGH requires approval.
                - "HIGH": nothing requires approval based on risk alone.

        blocked_operations:
            A mapping from operation type -> reason string. If an operation
            appears here, it is always blocked.

        notes:
            Optional human-readable description of this policy.
    """
    strict_mode: bool
    org_profile: str
    max_risk_without_approval: str
    blocked_operations: Dict[str, str]
    notes: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PolicyDecision:
    """
    Result of evaluating a single operation under a given policy.

    Attributes:
        allowed:
            If False, the operation must not be executed.

        requires_approval:
            If True, the operation must go through the Approvals Gateway.
            If False and allowed=True, it may proceed immediately.

        reason:
            Human-readable, deterministic explanation for logging/audit.

        effective_risk:
            Normalized risk level used for this decision.
    """
    allowed: bool
    requires_approval: bool
    reason: str
    effective_risk: str

    def __repr__(self) -> str:
        status = "ALLOWED" if self.allowed else "BLOCKED"
        gate = " (approval required)" if self.requires_approval else ""
        return f"<PolicyDecision {status}{gate} risk={self.effective_risk} reason={self.reason!r}>"


# ---------------------------------------------------------------------------
# Defaults & presets
# ---------------------------------------------------------------------------

def default_policy() -> PolicyConfig:
    """
    Default, reasonably safe policy for general projects.
    """
    return PolicyConfig(
        strict_mode=True,
        org_profile="DEFAULT",
        max_risk_without_approval="LOW",
        blocked_operations={
            # Explicitly block raw OS command execution outside sandbox
            "exec_shell_untrusted": "Untrusted shell execution is disabled.",
            "exec_code_untrusted": "Untrusted code execution is disabled.",
        },
        notes="Default Aether-One policy with strict mode enabled.",
    )


def fintech_policy() -> PolicyConfig:
    """
    Stricter defaults for fintech / financial systems.
    """
    cfg = default_policy()
    cfg.org_profile = "FINTECH"
    cfg.max_risk_without_approval = "LOW"
    cfg.blocked_operations.update(
        {
            "modify_payment_logic": "Payment and settlement logic changes require manual review.",
            "modify_risk_engine": "Risk engine modifications must go through manual approval and review.",
        }
    )
    cfg.notes = "Fintech-grade policy: strict mode, low tolerance for unapproved changes."
    return cfg


def healthcare_policy() -> PolicyConfig:
    """
    Strict defaults for healthcare / life-critical systems.
    """
    cfg = default_policy()
    cfg.org_profile = "HEALTHCARE"
    cfg.max_risk_without_approval = "LOW"
    cfg.blocked_operations.update(
        {
            "modify_clinical_logic": "Clinical decision logic is blocked by default.",
            "modify_device_interface": "Medical device integrations require manual engineering review.",
        }
    )
    cfg.notes = "Healthcare-grade policy: strict mode, highly conservative changes."
    return cfg


def preset_policy(profile: str) -> PolicyConfig:
    """
    Return a policy object for a named profile.
    """
    profile = (profile or "").strip().upper()
    if profile == "FINTECH":
        return fintech_policy()
    if profile == "HEALTHCARE":
        return healthcare_policy()
    return default_policy()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

DEFAULT_POLICY_FILENAME = ".aetherone_policy.json"


def load_policy(project_root: str, filename: str = DEFAULT_POLICY_FILENAME) -> PolicyConfig:
    """
    Load a PolicyConfig from JSON in the project root.

    If the file does not exist, a default policy is returned.
    """
    project_root_abs = os.path.abspath(os.path.expanduser(project_root))
    path = os.path.join(project_root_abs, filename)

    if not os.path.exists(path):
        # No policy file yet; use default.
        return default_policy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # On parse errors, fall back to a safe default.
        logger.warning("policy/engine: failed to parse policy file %s, using default: %s", path, e)
        cfg = default_policy()
        cfg.notes = f"Policy file could not be parsed: {e}. Default policy was applied."
        return cfg

    strict_mode = bool(data.get("strict_mode", True))
    org_profile = str(data.get("org_profile", "DEFAULT"))
    max_risk_without_approval = _normalize_risk(
        data.get("max_risk_without_approval", "LOW")
    )
    blocked_operations = dict(data.get("blocked_operations", {}))
    notes = data.get("notes")

    return PolicyConfig(
        strict_mode=strict_mode,
        org_profile=org_profile,
        max_risk_without_approval=max_risk_without_approval,
        blocked_operations=blocked_operations,
        notes=notes,
    )


def save_policy(project_root: str, policy: PolicyConfig, filename: str = DEFAULT_POLICY_FILENAME) -> str:
    """
    Save a PolicyConfig as JSON to the project root.

    Returns the absolute path to the saved file.
    """
    project_root_abs = os.path.abspath(os.path.expanduser(project_root))
    os.makedirs(project_root_abs, exist_ok=True)
    path = os.path.join(project_root_abs, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy.to_dict(), f, indent=2, sort_keys=True)

    return path


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _risk_index(level: str) -> int:
    lvl = _normalize_risk(level)
    return RISK_LEVELS.index(lvl)


def evaluate_operation(
    policy: PolicyConfig,
    operation_type: str,
    risk_level: str,
    is_guarded: bool,
) -> PolicyDecision:
    """
    Decide whether an operation is allowed and whether it requires approval.

    Parameters:
        policy:
            The PolicyConfig to apply.

        operation_type:
            String identifier for the operation, e.g.:
                "guarded_python_fix"
                "guarded_python_run"
                "exec_shell_untrusted"
                "modify_payment_logic"

        risk_level:
            "LOW", "MEDIUM", or "HIGH" (case-insensitive).
            Other values are treated as "HIGH".

        is_guarded:
            True if the operation goes through the guarded executor and
            approval gateway; False if it attempts a direct action.

    Rules (simplified, deterministic):

        1. If operation_type is explicitly blocked in policy.blocked_operations:
              -> allowed=False, requires_approval=False.

        2. If strict_mode is True and is_guarded is False:
              -> allowed=False, requires_approval=False.

        3. Normalize risk level to one of LOW/MEDIUM/HIGH.

        4. If risk_index(risk_level) > risk_index(max_risk_without_approval):
              -> allowed=True, requires_approval=True.

        5. Otherwise:
              -> allowed=True, requires_approval=False.
    """
    op = (operation_type or "").strip()
    effective_risk = _normalize_risk(risk_level)

    # 1. Explicitly blocked operations
    if op in policy.blocked_operations:
        reason = policy.blocked_operations[op] or "Operation is blocked by policy."
        return PolicyDecision(
            allowed=False,
            requires_approval=False,
            reason=f"Blocked operation '{op}': {reason}",
            effective_risk=effective_risk,
        )

    # 2. Strict mode: no unguarded operations
    if policy.strict_mode and not is_guarded:
        return PolicyDecision(
            allowed=False,
            requires_approval=False,
            reason=(
                f"Strict mode is enabled (profile={policy.org_profile}); "
                f"unguarded operation '{op}' is not allowed."
            ),
            effective_risk=effective_risk,
        )

    # 3. Risk-based approval
    risk_idx = _risk_index(effective_risk)
    max_idx = _risk_index(policy.max_risk_without_approval)

    if risk_idx > max_idx:
        # Allowed, but must go through Approval Gateway
        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            reason=(
                f"Operation '{op}' at risk '{effective_risk}' exceeds "
                f"max_risk_without_approval={policy.max_risk_without_approval}; "
                f"approval required."
            ),
            effective_risk=effective_risk,
        )

    # 4. Safe to proceed without explicit approval
    return PolicyDecision(
        allowed=True,
        requires_approval=False,
        reason=(
            f"Operation '{op}' at risk '{effective_risk}' is within "
            f"policy threshold (max_risk_without_approval={policy.max_risk_without_approval})."
        ),
        effective_risk=effective_risk,
    )


# ---------------------------------------------------------------------------
# AetherOS service wrapper (used by PipelineService and other callers)
# ---------------------------------------------------------------------------

_PLAN_RISK_MAP: Dict[str, str] = {
    "trial": "LOW",
    "starter": "LOW",
    "growth": "LOW",
    "enterprise": "LOW",
    "fintech": "MEDIUM",
    "healthcare": "MEDIUM",
}

_PLAN_PROFILE_MAP: Dict[str, str] = {
    "fintech": "FINTECH",
    "healthcare": "HEALTHCARE",
}


class AetherPolicyEngine:
    """
    High-level wrapper around the deterministic policy engine.
    Used by PipelineService, factory pipeline, and API handlers.
    All operations are synchronous (pure-python, no I/O).
    """

    def check_pipeline_start(self, org_id: str, plan: str) -> tuple[bool, str]:
        """
        Decide whether an org is allowed to start a new pipeline run.
        Returns (allowed: bool, reason: str).
        """
        plan_lower = (plan or "trial").lower()
        profile = _PLAN_PROFILE_MAP.get(plan_lower, "DEFAULT")
        risk = _PLAN_RISK_MAP.get(plan_lower, "LOW")
        policy = preset_policy(profile)

        decision = evaluate_operation(
            policy,
            operation_type="pipeline_start",
            risk_level=risk,
            is_guarded=True,
        )
        return decision.allowed, decision.reason

    def check_operation(
        self,
        org_id: str,
        plan: str,
        operation_type: str,
        risk_level: str = "MEDIUM",
        is_guarded: bool = True,
    ) -> tuple[bool, str]:
        """General-purpose operation check for any pipeline phase."""
        plan_lower = (plan or "trial").lower()
        profile = _PLAN_PROFILE_MAP.get(plan_lower, "DEFAULT")
        policy = preset_policy(profile)
        decision = evaluate_operation(policy, operation_type, risk_level, is_guarded)
        return decision.allowed, decision.reason


_policy_engine: Optional[AetherPolicyEngine] = None


def get_policy_engine() -> AetherPolicyEngine:
    """Return the singleton AetherPolicyEngine instance."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = AetherPolicyEngine()
    return _policy_engine

