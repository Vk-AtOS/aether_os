"""
AetherOS — Pipeline State Machine (26-phase factory edition)

States: IDLE → INTAKE → REQUIREMENTS → ARCHITECTURE → SCAFFOLDING →
        BACKEND_CODEGEN → UIUX_DESIGN → FRONTEND_CODEGEN → COMPONENT_LIBRARY →
        INTEGRATION → CODE_REVIEW → SECURITY → UNIT_TESTING → PERF_TESTING →
        A11Y_TESTING → E2E_TESTING → CICD → DOCUMENTATION → DEPLOYMENT →
        MONITORING → ERROR_TRACKING → ANALYTICS → ALERTING → FEATURE_FLAGS →
        AB_TESTING → APP_MEMORY → CLIENT_PORTAL → COMPLETE
        On-demand: CHANGE_REQUEST
        Terminal: FAILED, GATED_HUMAN
"""
from __future__ import annotations
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    IDLE              = "IDLE"
    INTAKE            = "INTAKE"
    REQUIREMENTS      = "REQUIREMENTS"
    ARCHITECTURE      = "ARCHITECTURE"
    SCAFFOLDING       = "SCAFFOLDING"
    BACKEND_CODEGEN   = "BACKEND_CODEGEN"
    UIUX_DESIGN       = "UIUX_DESIGN"
    FRONTEND_CODEGEN  = "FRONTEND_CODEGEN"
    COMPONENT_LIBRARY = "COMPONENT_LIBRARY"
    INTEGRATION       = "INTEGRATION"
    CODE_REVIEW       = "CODE_REVIEW"
    SECURITY          = "SECURITY"
    UNIT_TESTING      = "UNIT_TESTING"
    PERF_TESTING      = "PERF_TESTING"
    A11Y_TESTING      = "A11Y_TESTING"
    E2E_TESTING       = "E2E_TESTING"
    CICD              = "CICD"
    DOCUMENTATION     = "DOCUMENTATION"
    DEPLOYMENT        = "DEPLOYMENT"
    MONITORING        = "MONITORING"
    ERROR_TRACKING    = "ERROR_TRACKING"
    ANALYTICS         = "ANALYTICS"
    ALERTING          = "ALERTING"
    FEATURE_FLAGS     = "FEATURE_FLAGS"
    AB_TESTING        = "AB_TESTING"
    APP_MEMORY        = "APP_MEMORY"
    CLIENT_PORTAL     = "CLIENT_PORTAL"
    CHANGE_REQUEST    = "CHANGE_REQUEST"
    COMPLETE          = "COMPLETE"
    FAILED            = "FAILED"
    GATED_HUMAN       = "GATED_HUMAN"


# Ordered main pipeline sequence (26 phases)
PIPELINE_SEQUENCE: List[PipelineState] = [
    PipelineState.INTAKE,
    PipelineState.REQUIREMENTS,
    PipelineState.ARCHITECTURE,
    PipelineState.SCAFFOLDING,
    PipelineState.BACKEND_CODEGEN,
    PipelineState.UIUX_DESIGN,
    PipelineState.FRONTEND_CODEGEN,
    PipelineState.COMPONENT_LIBRARY,
    PipelineState.INTEGRATION,
    PipelineState.CODE_REVIEW,
    PipelineState.SECURITY,
    PipelineState.UNIT_TESTING,
    PipelineState.PERF_TESTING,
    PipelineState.A11Y_TESTING,
    PipelineState.E2E_TESTING,
    PipelineState.CICD,
    PipelineState.DOCUMENTATION,
    PipelineState.DEPLOYMENT,
    PipelineState.MONITORING,
    PipelineState.ERROR_TRACKING,
    PipelineState.ANALYTICS,
    PipelineState.ALERTING,
    PipelineState.FEATURE_FLAGS,
    PipelineState.AB_TESTING,
    PipelineState.APP_MEMORY,
    PipelineState.CLIENT_PORTAL,
]

# Phase name → state mapping
# Includes both the current 20-phase pipeline names and legacy phase names.
# PIPELINE-053: all 20 PHASE_SEQUENCE entries map to a state; extra states in
# PipelineState (IDLE, CHANGE_REQUEST, COMPLETE, FAILED, GATED_HUMAN) are
# terminal/special — not pipeline phases — so state count > phase count is correct.
PHASE_TO_STATE: Dict[str, PipelineState] = {
    # ── Current 20-phase factory pipeline ─────────────────────────────────────
    "p01_intake_requirements": PipelineState.REQUIREMENTS,
    "p02_architecture":        PipelineState.ARCHITECTURE,
    "p03_scaffolding":         PipelineState.SCAFFOLDING,
    "p04_backend":             PipelineState.BACKEND_CODEGEN,
    "p05_frontend":            PipelineState.FRONTEND_CODEGEN,
    "p06_review_security":     PipelineState.SECURITY,
    "p07_testing":             PipelineState.UNIT_TESTING,
    "p07b_self_healing":       PipelineState.UNIT_TESTING,   # self-healing runs in testing state
    "p08_cicd_deployment":     PipelineState.CICD,
    "p09_observability":       PipelineState.MONITORING,
    "p10_docs_delivery":       PipelineState.DOCUMENTATION,
    "p11_deployment":          PipelineState.DEPLOYMENT,
    # Post-deployment phases (8 of the 20)
    "p11a_monitoring":         PipelineState.MONITORING,
    "p11b_error_tracking":     PipelineState.ERROR_TRACKING,
    "p11c_analytics":          PipelineState.ANALYTICS,
    "p11d_alerting":           PipelineState.ALERTING,
    "p12a_feature_flags":      PipelineState.FEATURE_FLAGS,
    "p12b_ab_testing":         PipelineState.AB_TESTING,
    "p13_app_memory":          PipelineState.APP_MEMORY,
    "p14_client_portal":       PipelineState.CLIENT_PORTAL,
    # ── Legacy phase names (kept for partial re-runs and history) ─────────────
    "p00_intake":               PipelineState.INTAKE,
    "p01_requirements":         PipelineState.REQUIREMENTS,
    "p04a_backend_codegen":     PipelineState.BACKEND_CODEGEN,
    "p04b_uiux_design":         PipelineState.UIUX_DESIGN,
    "p04c_frontend_codegen":    PipelineState.FRONTEND_CODEGEN,
    "p04d_component_library":   PipelineState.COMPONENT_LIBRARY,
    "p04e_integration":         PipelineState.INTEGRATION,
    "p05_code_review":          PipelineState.CODE_REVIEW,
    "p06_security":             PipelineState.SECURITY,
    "p07a_unit_testing":        PipelineState.UNIT_TESTING,
    "p07b_performance_testing": PipelineState.PERF_TESTING,
    "p07c_accessibility_testing": PipelineState.A11Y_TESTING,
    "p07d_e2e_testing":         PipelineState.E2E_TESTING,
    "p08_cicd":                 PipelineState.CICD,
    "p09_documentation":        PipelineState.DOCUMENTATION,
    "p10_deployment":           PipelineState.DEPLOYMENT,
    "p15_change_requests":      PipelineState.CHANGE_REQUEST,
}

_TERMINAL = {PipelineState.COMPLETE, PipelineState.FAILED}
_ANY_PHASE = set(PIPELINE_SEQUENCE)

# Build transitions: each phase → next phase + FAILED + GATED_HUMAN
_TRANSITIONS: Dict[PipelineState, List[PipelineState]] = {
    PipelineState.IDLE: [PipelineState.INTAKE, PipelineState.REQUIREMENTS],
}
for i, state in enumerate(PIPELINE_SEQUENCE):
    nxt = [PipelineState.FAILED, PipelineState.GATED_HUMAN]
    if i + 1 < len(PIPELINE_SEQUENCE):
        nxt.insert(0, PIPELINE_SEQUENCE[i + 1])
    else:
        nxt.insert(0, PipelineState.COMPLETE)
    # Allow going back to any earlier phase (for change requests)
    nxt.extend(PIPELINE_SEQUENCE[:i])
    _TRANSITIONS[state] = list(dict.fromkeys(nxt))  # dedupe

_TRANSITIONS[PipelineState.GATED_HUMAN] = list(PIPELINE_SEQUENCE) + [PipelineState.FAILED]
_TRANSITIONS[PipelineState.CHANGE_REQUEST] = list(PIPELINE_SEQUENCE) + [PipelineState.FAILED]
_TRANSITIONS[PipelineState.COMPLETE] = []
_TRANSITIONS[PipelineState.FAILED] = []


class StateTransitionError(RuntimeError):
    pass


class PipelineStateMachine:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.current_state = PipelineState.IDLE
        self.history: List[Dict[str, Any]] = []
        self._state_entered_at: float = time.time()

    def transition_to(self, new_state: PipelineState, reason: str = "",
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        allowed = _TRANSITIONS.get(self.current_state, [])
        if new_state not in allowed:
            raise StateTransitionError(
                f"Invalid transition: {self.current_state} → {new_state}. "
                f"Allowed: {[s.value for s in allowed[:5]]}..."
            )
        duration = time.time() - self._state_entered_at
        record = {
            "run_id": self.run_id, "from_state": self.current_state.value,
            "to_state": new_state.value, "reason": reason,
            "duration_in_from_state": round(duration, 3),
            "timestamp": time.time(), "metadata": metadata or {},
        }
        self.history.append(record)
        try:
            from aether_os.core.audit.logger import get_audit_logger
            get_audit_logger().log_sync(
                actor="state_machine", action="state_transition",
                details=record, session_id=self.run_id,
            )
        except Exception:
            pass
        old = self.current_state
        self.current_state = new_state
        self._state_entered_at = time.time()
        logger.info("[SM run=%s] %s → %s | %s", self.run_id,
                    old.value, new_state.value, reason)

    def next_phase(self) -> Optional[PipelineState]:
        if self.current_state not in PIPELINE_SEQUENCE:
            return None
        idx = PIPELINE_SEQUENCE.index(self.current_state)
        return PIPELINE_SEQUENCE[idx + 1] if idx + 1 < len(PIPELINE_SEQUENCE) else PipelineState.COMPLETE

    def is_terminal(self) -> bool:
        return self.current_state in _TERMINAL

    def is_gated(self) -> bool:
        return self.current_state == PipelineState.GATED_HUMAN

    def elapsed_in_current_state(self) -> float:
        return time.time() - self._state_entered_at

    def summary(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "current_state": self.current_state.value,
            "transitions": len(self.history),
            "elapsed_in_state": round(self.elapsed_in_current_state(), 2),
        }

    def get_resume_state(self) -> Optional[PipelineState]:
        completed = [h for h in self.history
                     if h["to_state"] not in ("FAILED", "GATED_HUMAN")]
        if not completed:
            return None
        try:
            return PipelineState(completed[-1]["to_state"])
        except ValueError:
            return None
