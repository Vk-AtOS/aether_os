"""
Aether-One Multi-Agent Base Definitions

This module defines the base classes and enums for all internal and product
agents in Aether-One. It is intentionally self-contained so that all other
agent implementations can import from here without circular dependencies.
"""

from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentKind(str, Enum):
    INTERNAL = "internal"
    PRODUCT = "product"


class AgentName(str, Enum):
    """
    Canonical names for all agents in the system.

    Internal Agents (always running):
        - POLICY
        - RISK
        - SNAPSHOT
        - MEMORY_KNOWLEDGE
        - RED_TEAM
        - STABILITY_GUARDIAN
        - SYSTEM_SPEC_PROFILER
        - BUS_NETWORK_MANAGER

    Product Agents (developer-visible):
        - FIX_ENGINE
        - CODE_REVIEW
        - TEST
        - REFACTOR
        - SECURITY_ANALYZER
        - REPO_REASONING
    """

    # Internal agents
    POLICY = "policy_agent"
    RISK = "risk_agent"
    SNAPSHOT = "snapshot_agent"
    MEMORY_KNOWLEDGE = "memory_knowledge_agent"
    RED_TEAM = "red_team_safety_agent"
    STABILITY_GUARDIAN = "stability_guardian_agent"
    SYSTEM_SPEC_PROFILER = "system_spec_profiler_agent"
    BUS_NETWORK_MANAGER = "bus_network_manager_agent"

    # Product agents
    FIX_ENGINE = "fix_engine_agent"
    CODE_REVIEW = "code_review_agent"
    TEST = "test_agent"
    REFACTOR = "refactor_agent"
    SECURITY_ANALYZER = "security_analyzer_agent"
    REPO_REASONING = "repo_reasoning_agent"


@dataclass
class AgentContext:
    """
    Context passed into agents.

    This is intentionally generic so that different workflows can pass
    additional keys in the `metadata` dictionary without changing the type.
    """

    project_path: str
    file_path: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Arbitrary metadata: error traces, diffs, config, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Deadline / timeout in seconds for this agent run (optional)
    deadline_ts: Optional[float] = None

    def with_metadata(self, **extra: Any) -> "AgentContext":
        new_meta = dict(self.metadata)
        new_meta.update(extra)
        return AgentContext(
            project_path=self.project_path,
            file_path=self.file_path,
            workflow_id=self.workflow_id,
            user_id=self.user_id,
            request_id=self.request_id,
            metadata=new_meta,
            deadline_ts=self.deadline_ts,
        )

    def remaining_time(self) -> Optional[float]:
        if self.deadline_ts is None:
            return None
        return max(0.0, self.deadline_ts - time.time())


@dataclass
class AgentResult:
    """
    Standard result structure from any agent.

    `status`:
        - "ok"       → successful completion
        - "error"    → agent failed internally
        - "skipped"  → agent chose not to act
        - "blocked"  → blocked by policy/safety
    """

    agent_name: AgentName
    status: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)
    started_ts: float = field(default_factory=time.time)
    finished_ts: float = field(default_factory=time.time)

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_ts - self.started_ts)


class Agent(abc.ABC):
    """
    Base class for all Aether-One agents.

    Implementations should override `run()` and can optionally override
    `can_handle()` for routing/filtering in the agent mesh.
    """

    name: AgentName
    kind: AgentKind

    def __init__(self, name: AgentName, kind: AgentKind) -> None:
        self.name = name
        self.kind = kind

    @abc.abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:
        """
        Execute the agent logic.

        Implementations must set `finished_ts` on the result before returning.
        """
        raise NotImplementedError

    def can_handle(self, ctx: AgentContext) -> bool:
        """
        Optional filter hook for routing.

        Agent Mesh can use this to quickly skip agents that don't apply to a
        given context, e.g. language or project type filters.
        """
        return True


class AgentRegistry:
    """
    Simple in-process registry for agents.

    This allows the orchestrator and the future Neural Agent Mesh to discover
    agents by name and iterate over subsets (internal/product).
    """

    def __init__(self) -> None:
        self._by_name: Dict[AgentName, Agent] = {}

    def register(self, agent: Agent) -> None:
        if agent.name in self._by_name:
            raise ValueError(f"Agent {agent.name} already registered")
        self._by_name[agent.name] = agent

    def get(self, name: AgentName) -> Optional[Agent]:
        return self._by_name.get(name)

    def all(self) -> List[Agent]:
        return list(self._by_name.values())

    def internal_agents(self) -> List[Agent]:
        return [a for a in self._by_name.values() if a.kind == AgentKind.INTERNAL]

    def product_agents(self) -> List[Agent]:
        return [a for a in self._by_name.values() if a.kind == AgentKind.PRODUCT]


# Global default registry instance used by the rest of the system.
default_agent_registry = AgentRegistry()

