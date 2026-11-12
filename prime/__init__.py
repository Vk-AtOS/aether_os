"""Prime — deterministic authorisation core (no model calls). Execution happens only in
prime/executors.py, after prime/approvals.py has checked the approval."""
from .authz import (
    ACTION_TYPES,
    MAX_DELEGATION_DURATION,
    NEVER,
    PAYMENT_CEILING,
    Action,
    AutonomyLevel,
    Decision,
    Delegation,
    Limits,
    Outcome,
    authorize,
)
from .repository import DelegationRepository
from .executors import Executor
from .service import PrimeService

__all__ = [
    "ACTION_TYPES", "MAX_DELEGATION_DURATION", "NEVER", "PAYMENT_CEILING",
    "Action", "AutonomyLevel", "Decision", "Delegation", "Limits", "Outcome",
    "authorize", "DelegationRepository", "Executor", "PrimeService",
]
