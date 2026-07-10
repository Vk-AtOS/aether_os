"""
AetherOS — Shared Pipeline Execution Context
NEW module. Typed Pydantic model passed between all phases.

Supersedes aether2's ExecutionContext dataclass with full typed fields for all 10 phases.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class PhaseOutput(BaseModel):
    """Generic typed output from a single phase."""
    phase_id: str
    phase_name: str
    passed: bool = False
    confidence: float = 0.0
    issues: List[str] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0


class ExecutionContext(BaseModel):
    """
    Shared execution context passed through the entire AetherOS pipeline.

    Mutated by each phase. Serialisable to JSON for persistence / resumption.
    All optional fields are None until the phase that sets them runs.
    """

    # Unique identifiers
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: Optional[str] = None  # Multi-tenancy support

    # Input
    requirement: str = ""          # Original NL requirement from user
    domain: str = "general"        # Added field
    tech_stack: Dict[str, Any] = Field(default_factory=dict) # Added field
    language: str = "python"       # Target programming language
    project_name: str = "untitled"
    output_dir: Optional[str] = None  # Where generated code is written (Bug 9 fix)

    # Phase outputs (set as pipeline progresses)
    requirements_doc: Optional[str] = None          # p01
    architecture_doc: Optional[str] = None          # p02
    scaffold_manifest: Optional[Dict[str, Any]] = None  # p03
    generated_code: Optional[str] = None            # p04
    review_findings: Optional[List[str]] = None     # p05
    security_report: Optional[Dict[str, Any]] = None  # p06
    test_results: Optional[Dict[str, Any]] = None   # p07
    ci_result: Optional[Dict[str, Any]] = None      # p08
    observability_config: Optional[Dict[str, Any]] = None  # p09_observability
    docs: Optional[str] = None                      # p10
    packaging_artifact: Optional[str] = None        # p11

    # Retry state
    retry_count: int = 0
    max_retries: int = 3
    security_issues: Optional[List[Dict[str, Any]]] = None  # from security phase
    test_failures: Optional[str] = None             # from test phase

    # Phase history
    phase_outputs: List[PhaseOutput] = Field(default_factory=list)

    # Errors
    errors: List[str] = Field(default_factory=list)

    # Arbitrary metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Approval
    approval_ticket_id: Optional[str] = None
    human_approved: Optional[bool] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        logger.warning("Pipeline error recorded [run=%s]: %s", self.run_id, error)

    def record_phase(self, output: PhaseOutput) -> None:
        self.phase_outputs.append(output)
        status = "PASS" if output.passed else "FAIL"
        logger.info(
            "Phase %s [%s] confidence=%.2f issues=%d",
            output.phase_name, status, output.confidence, len(output.issues),
        )

    def get_phase_output(self, phase_id: str) -> Optional[PhaseOutput]:
        for p in self.phase_outputs:
            if p.phase_id == phase_id:
                return p
        return None

    def summary(self) -> Dict[str, Any]:
        """Return a human-readable summary of pipeline progress."""
        return {
            "run_id": self.run_id,
            "requirement": self.requirement[:100],
            "phases_completed": len(self.phase_outputs),
            "errors": len(self.errors),
            "has_code": self.generated_code is not None,
            "has_tests": self.test_results is not None,
            "has_docs": self.docs is not None,
        }
