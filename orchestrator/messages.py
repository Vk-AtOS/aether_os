"""AetherOS — Inter-phase message types for the message bus."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class PhaseInput(BaseModel):
    run_id: str
    project_id: str
    phase: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_dir: str
    domain: str = "general"
    client_id: str
    is_change_request: bool = False
    change_context: Optional[Dict[str, Any]] = None
    memory_context: List[Dict[str, Any]] = Field(default_factory=list)


class PhaseResult(BaseModel):
    run_id: str
    phase: str
    status: Literal["passed", "failed", "escalated", "upstream"]
    output_path: str = ""
    confidence: float = 0.0
    issues: List[str] = Field(default_factory=list)
    next_phase: Optional[str] = None
    upstream_route: Optional[str] = None
    failure_context: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class PhaseMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    from_phase: str
    to_phase: Optional[str] = None
    result: PhaseResult
