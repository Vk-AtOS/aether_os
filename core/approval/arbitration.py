"""
Arbitration & Conflict Resolution for Aether-One

Handles conflicts between agents, policy violations, and escalation to human approval.

RESPONSIBILITIES:
- Resolve agent disagreements
- Arbitrate resource conflicts
- Enforce policy vetoes
- Escalate critical decisions to human approval
- Maintain audit trail of all arbitration decisions

GUARANTEES:
- Deterministic conflict resolution
- Human approval for critical decisions
- Full audit trail
- Policy-driven decision making
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("aetherone.arbitration")


class ConflictType(str, Enum):
    """Types of conflicts that can occur."""
    
    AGENT_DISAGREEMENT = "agent_disagreement"
    RESOURCE_CONFLICT = "resource_conflict"
    POLICY_VIOLATION = "policy_violation"
    SECURITY_CONCERN = "security_concern"
    QUALITY_THRESHOLD = "quality_threshold"
    PRIORITY_CONFLICT = "priority_conflict"


class ResolutionStrategy(str, Enum):
    """Strategies for resolving conflicts."""
    
    HIGHEST_PRIORITY = "highest_priority"
    POLICY_OVERRIDE = "policy_override"
    HUMAN_APPROVAL = "human_approval"
    CONSENSUS = "consensus"
    DETERMINISTIC_VOTE = "deterministic_vote"
    SAFETY_FIRST = "safety_first"


class ResolutionStatus(str, Enum):
    """Status of conflict resolution."""
    
    PENDING = "pending"
    AUTO_RESOLVED = "auto_resolved"
    AWAITING_HUMAN = "awaiting_human"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    POLICY_BLOCKED = "policy_blocked"


@dataclass
class ConflictingProposal:
    """A proposal from an agent that conflicts with others."""
    
    agent_name: str
    proposal_id: str
    priority: int
    confidence: float  # 0.0 to 1.0
    rationale: str
    payload: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_name": self.agent_name,
            "proposal_id": self.proposal_id,
            "priority": self.priority,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "payload": self.payload,
        }


@dataclass
class Conflict:
    """A conflict requiring arbitration."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    type: ConflictType = ConflictType.AGENT_DISAGREEMENT
    description: str = ""
    proposals: List[ConflictingProposal] = field(default_factory=list)
    
    # Context
    project_path: Optional[str] = None
    file_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Resolution
    status: ResolutionStatus = ResolutionStatus.PENDING
    resolution_strategy: Optional[ResolutionStrategy] = None
    chosen_proposal: Optional[ConflictingProposal] = None
    rationale: str = ""
    
    # Timing
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    
    # Human approval
    requires_human_approval: bool = False
    human_approver: Optional[str] = None
    human_decision: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "proposals": [p.to_dict() for p in self.proposals],
            "project_path": self.project_path,
            "file_path": self.file_path,
            "metadata": self.metadata,
            "status": self.status.value,
            "resolution_strategy": self.resolution_strategy.value if self.resolution_strategy else None,
            "chosen_proposal": self.chosen_proposal.to_dict() if self.chosen_proposal else None,
            "rationale": self.rationale,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "requires_human_approval": self.requires_human_approval,
            "human_approver": self.human_approver,
            "human_decision": self.human_decision,
        }


@dataclass
class ArbitrationPolicy:
    """Policy for arbitration decisions."""
    
    # Auto-resolution thresholds
    min_confidence_for_auto: float = 0.8
    min_consensus_for_auto: float = 0.7
    
    # Human approval requirements
    require_human_for_security: bool = True
    require_human_for_policy_violation: bool = True
    require_human_for_low_confidence: bool = True
    low_confidence_threshold: float = 0.5
    
    # Safety settings
    safety_first_mode: bool = True
    block_on_policy_violation: bool = True
    
    def should_require_human(self, conflict: Conflict) -> bool:
        """Determine if conflict requires human approval."""
        # Security concerns always require human approval
        if self.require_human_for_security and conflict.type == ConflictType.SECURITY_CONCERN:
            return True
        
        # Policy violations require human approval
        if self.require_human_for_policy_violation and conflict.type == ConflictType.POLICY_VIOLATION:
            return True
        
        # Low confidence proposals require human approval
        if self.require_human_for_low_confidence:
            for proposal in conflict.proposals:
                if proposal.confidence < self.low_confidence_threshold:
                    return True
        
        return False


class Arbitrator:
    """
    Arbitrator for conflict resolution.
    
    Handles conflicts between agents and enforces policy decisions.
    """
    
    def __init__(
        self,
        policy: Optional[ArbitrationPolicy] = None,
        enable_audit_log: bool = True,
        audit_log_dir: Optional[Path] = None,
        seed: int = 42,
    ):
        """
        Initialize arbitrator.
        
        Args:
            policy: Arbitration policy (uses default if None)
            enable_audit_log: Enable audit logging
            audit_log_dir: Directory for audit logs
            seed: Seed for deterministic conflict resolution
        """
        self.policy = policy or ArbitrationPolicy()
        self.seed = seed
        self.enable_audit_log = enable_audit_log
        self.audit_log_dir = audit_log_dir or Path.home() / ".aetherone" / "arbitration"
        
        # Conflict tracking
        self.pending_conflicts: List[Conflict] = []
        self.resolved_conflicts: List[Conflict] = []
        
        # Audit log
        self.audit_log: Optional[Path] = None
        if self.enable_audit_log:
            self.audit_log_dir.mkdir(parents=True, exist_ok=True)
            self.audit_log = self.audit_log_dir / f"arbitration_{int(time.time())}.jsonl"
        
        logger.info(f"Arbitrator initialized: seed={self.seed}, audit_log={'enabled' if enable_audit_log else 'disabled'}")
    
    def submit_conflict(self, conflict: Conflict) -> str:
        """
        Submit a conflict for arbitration.
        
        Args:
            conflict: Conflict to arbitrate
        
        Returns:
            Conflict ID
        """
        self.pending_conflicts.append(conflict)
        
        # Log submission
        self._log_event("conflict_submitted", conflict.to_dict())
        
        logger.info(f"Conflict submitted: {conflict.type.value} - {conflict.description}")
        
        return conflict.id
    
    def resolve_conflict(self, conflict_id: str) -> Optional[Conflict]:
        """
        Resolve a conflict using appropriate strategy.
        
        Args:
            conflict_id: ID of conflict to resolve
        
        Returns:
            Resolved conflict, or None if not found
        """
        # Find conflict
        conflict = None
        for i, c in enumerate(self.pending_conflicts):
            if c.id == conflict_id:
                conflict = self.pending_conflicts.pop(i)
                break
        
        if not conflict:
            logger.warning(f"Conflict not found: {conflict_id}")
            return None
        
        # Check if human approval required
        if self.policy.should_require_human(conflict):
            conflict.requires_human_approval = True
            conflict.status = ResolutionStatus.AWAITING_HUMAN
            conflict.resolution_strategy = ResolutionStrategy.HUMAN_APPROVAL
            
            # Put back in pending queue
            self.pending_conflicts.append(conflict)
            
            logger.info(f"Conflict requires human approval: {conflict.id}")
            self._log_event("awaiting_human", conflict.to_dict())
            
            return conflict
        
        # Auto-resolve based on strategy
        strategy = self._select_strategy(conflict)
        conflict.resolution_strategy = strategy
        
        if strategy == ResolutionStrategy.POLICY_OVERRIDE:
            self._resolve_by_policy(conflict)
            # Policy override may block, don't mark as auto-resolved
            if conflict.status == ResolutionStatus.POLICY_BLOCKED:
                self.resolved_conflicts.append(conflict)
                self._log_event("conflict_blocked", conflict.to_dict())
                return conflict
        elif strategy == ResolutionStrategy.HIGHEST_PRIORITY:
            self._resolve_by_priority(conflict)
        elif strategy == ResolutionStrategy.CONSENSUS:
            self._resolve_by_consensus(conflict)
        elif strategy == ResolutionStrategy.DETERMINISTIC_VOTE:
            self._resolve_by_deterministic_vote(conflict)
        elif strategy == ResolutionStrategy.SAFETY_FIRST:
            self._resolve_by_safety_first(conflict)
        else:
            # Default: highest confidence
            self._resolve_by_confidence(conflict)
        
        # Mark as resolved
        conflict.status = ResolutionStatus.AUTO_RESOLVED
        conflict.resolved_at = time.time()
        self.resolved_conflicts.append(conflict)
        
        # Log resolution
        self._log_event("conflict_resolved", conflict.to_dict())
        
        logger.info(
            f"Conflict resolved: {conflict.id} - "
            f"strategy={strategy.value}, "
            f"chosen={conflict.chosen_proposal.agent_name if conflict.chosen_proposal else 'none'}"
        )
        
        return conflict
    
    def _select_strategy(self, conflict: Conflict) -> ResolutionStrategy:
        """Select appropriate resolution strategy."""
        # Security concerns: safety first
        if conflict.type == ConflictType.SECURITY_CONCERN:
            return ResolutionStrategy.SAFETY_FIRST
        
        # Policy violations: policy override
        if conflict.type == ConflictType.POLICY_VIOLATION:
            return ResolutionStrategy.POLICY_OVERRIDE
        
        # Resource conflicts: highest priority
        if conflict.type == ConflictType.RESOURCE_CONFLICT:
            return ResolutionStrategy.HIGHEST_PRIORITY
        
        # Agent disagreements: use confidence if different priorities, else deterministic vote
        if conflict.type == ConflictType.AGENT_DISAGREEMENT:
            priorities = [p.priority for p in conflict.proposals]
            if len(set(priorities)) > 1:
                return ResolutionStrategy.HIGHEST_PRIORITY
            return ResolutionStrategy.DETERMINISTIC_VOTE
        
        # Default: highest priority
        return ResolutionStrategy.HIGHEST_PRIORITY
    
    def _resolve_by_priority(self, conflict: Conflict) -> None:
        """Resolve by choosing highest priority proposal."""
        if not conflict.proposals:
            return
        
        # Sort by priority (highest first)
        sorted_proposals = sorted(
            conflict.proposals,
            key=lambda p: p.priority,
            reverse=True
        )
        
        conflict.chosen_proposal = sorted_proposals[0]
        conflict.rationale = f"Selected highest priority proposal from {conflict.chosen_proposal.agent_name}"
    
    def _resolve_by_confidence(self, conflict: Conflict) -> None:
        """Resolve by choosing highest confidence proposal."""
        if not conflict.proposals:
            return
        
        # Sort by confidence (highest first)
        sorted_proposals = sorted(
            conflict.proposals,
            key=lambda p: p.confidence,
            reverse=True
        )
        
        conflict.chosen_proposal = sorted_proposals[0]
        conflict.rationale = f"Selected highest confidence proposal ({conflict.chosen_proposal.confidence:.2f}) from {conflict.chosen_proposal.agent_name}"
    
    def _resolve_by_consensus(self, conflict: Conflict) -> None:
        """Resolve by finding consensus among proposals."""
        if not conflict.proposals:
            return
        
        # For now, use confidence-weighted vote
        # In a real implementation, this would analyze proposal similarity
        self._resolve_by_confidence(conflict)
        conflict.rationale = f"Consensus resolution: {conflict.chosen_proposal.agent_name}"
    
    def _resolve_by_deterministic_vote(self, conflict: Conflict) -> None:
        """Resolve using deterministic voting based on seed."""
        if not conflict.proposals:
            return
        
        # Create deterministic hash based on conflict ID and seed
        vote_input = f"{self.seed}:{conflict.id}:{len(conflict.proposals)}"
        vote_hash = hashlib.sha256(vote_input.encode()).digest()
        vote_index = int.from_bytes(vote_hash[:4], byteorder='big') % len(conflict.proposals)
        
        conflict.chosen_proposal = conflict.proposals[vote_index]
        conflict.rationale = f"Deterministic vote selected {conflict.chosen_proposal.agent_name}"
    
    def _resolve_by_safety_first(self, conflict: Conflict) -> None:
        """Resolve by choosing safest proposal (lowest risk)."""
        if not conflict.proposals:
            return
        
        # Choose proposal with highest confidence (assuming high confidence = lower risk)
        # In a real implementation, this would use explicit risk scores
        self._resolve_by_confidence(conflict)
        conflict.rationale = f"Safety-first resolution: {conflict.chosen_proposal.agent_name}"
    
    def _resolve_by_policy(self, conflict: Conflict) -> None:
        """Resolve using policy override."""
        # Block all proposals if policy violation
        conflict.status = ResolutionStatus.POLICY_BLOCKED
        conflict.rationale = "Blocked by policy violation"
        logger.warning(f"Conflict blocked by policy: {conflict.id}")
    
    def submit_human_decision(
        self,
        conflict_id: str,
        chosen_agent_name: str,
        approver: str,
        decision_notes: str = ""
    ) -> Optional[Conflict]:
        """
        Submit human decision for a conflict.
        
        Args:
            conflict_id: Conflict ID
            chosen_agent_name: Name of chosen agent
            approver: User who made the decision
            decision_notes: Optional notes about decision
        
        Returns:
            Resolved conflict, or None if not found
        """
        # Find conflict
        conflict = None
        for i, c in enumerate(self.pending_conflicts):
            if c.id == conflict_id:
                conflict = self.pending_conflicts.pop(i)
                break
        
        if not conflict:
            logger.warning(f"Conflict not found: {conflict_id}")
            return None
        
        # Find chosen proposal
        chosen = None
        for proposal in conflict.proposals:
            if proposal.agent_name == chosen_agent_name:
                chosen = proposal
                break
        
        if not chosen:
            logger.warning(f"Proposal not found: {chosen_agent_name}")
            # Put back in pending
            self.pending_conflicts.append(conflict)
            return None
        
        # Apply human decision
        conflict.chosen_proposal = chosen
        conflict.status = ResolutionStatus.HUMAN_APPROVED
        conflict.human_approver = approver
        conflict.human_decision = decision_notes
        conflict.resolved_at = time.time()
        conflict.rationale = f"Human approved: {chosen_agent_name} (by {approver})"
        
        self.resolved_conflicts.append(conflict)
        
        # Log human decision
        self._log_event("human_decision", conflict.to_dict())
        
        logger.info(f"Human decision recorded: {conflict.id} - {chosen_agent_name} by {approver}")
        
        return conflict
    
    def get_pending_conflicts(self) -> List[Conflict]:
        """Get list of pending conflicts."""
        return list(self.pending_conflicts)
    
    def get_conflicts_awaiting_human(self) -> List[Conflict]:
        """Get conflicts awaiting human approval."""
        return [c for c in self.pending_conflicts if c.status == ResolutionStatus.AWAITING_HUMAN]
    
    def _log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log event to audit log."""
        if not self.enable_audit_log or not self.audit_log:
            return
        
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        
        try:
            with open(self.audit_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")


# Global arbitrator instance
_global_arbitrator: Optional[Arbitrator] = None


def get_global_arbitrator() -> Arbitrator:
    """Get or create global arbitrator instance."""
    global _global_arbitrator
    if _global_arbitrator is None:
        _global_arbitrator = Arbitrator()
    return _global_arbitrator
