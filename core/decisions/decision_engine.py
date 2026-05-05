import uuid
import time
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from sqlalchemy import String, ForeignKey, Float, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

@dataclass
class Decision:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    org_id: str = ""
    decision_type: str = ""
    title: str = ""
    what: str = ""
    why: str = ""
    alternatives: List[str] = field(default_factory=list)
    impact: str = ""
    phase: str = ""
    status: str = "pending"
    human_choice: Optional[str] = None
    timeout_seconds: int = 300
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None

class DecisionEngine:
    def __init__(self, db_session):
        self.session = db_session

    async def request_approval(self, decision: Decision) -> Decision:
        # TODO: Save to DB, emit event, wait for approval
        return decision

    async def approve_decision(self, decision_id: str, choice: Optional[str] = None):
        pass

_engine: Optional[DecisionEngine] = None

def get_decision_engine(db_session) -> DecisionEngine:
    global _engine
    if _engine is None:
        _engine = DecisionEngine(db_session)
    return _engine
