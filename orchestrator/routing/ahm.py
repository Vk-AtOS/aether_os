"""
Adaptive Hybrid Mesh (AHM) - Aether-One Primary Routing Brain

The AHM is the single authoritative routing system for Aether-One v1.1.0+.
It replaces parallel routing approaches with a unified, deterministic,
offline-only agent coordination layer.

Key Features:
- Deterministic routing based on agent capabilities and health
- Offline-only operation (no network calls)
- Optional WAL (Write-Ahead Log) for audit trail (default: OFF)
- Health monitoring and degradation detection
- Graceful fallback mechanisms
- Backward compatible with legacy mesh API

Architecture:
- Routes agent requests based on context and agent health scores
- Maintains agent health metrics offline
- Provides fallback routing when primary agents fail
- Logs all routing decisions to optional WAL for auditability

System Guarantees:
- No network calls
- Deterministic routing (same input → same output)
- Auditable (optional WAL logging)
- Backward compatible with existing orchestrator APIs
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    Agent,
    AgentContext,
    AgentName,
    AgentRegistry,
    AgentResult,
    default_agent_registry,
)
from ..comm.message import Message, MessageType, MessagePriority

logger = logging.getLogger("aetherone.ahm")


@dataclass
class AgentHealthScore:
    """Health score for an agent in the mesh."""
    
    agent_name: str
    score: float  # 0.0 (dead) to 1.0 (perfect health)
    recent_successes: int = 0
    recent_failures: int = 0
    last_success_ts: Optional[float] = None
    last_failure_ts: Optional[float] = None
    degraded: bool = False
    degradation_reason: Optional[str] = None
    
    def update_success(self) -> None:
        """Record successful execution."""
        self.recent_successes += 1
        self.last_success_ts = time.time()
        # Recalculate score
        self._recalculate_score()
    
    def update_failure(self, reason: str = "") -> None:
        """Record failed execution."""
        self.recent_failures += 1
        self.last_failure_ts = time.time()
        self.degradation_reason = reason
        # Recalculate score
        self._recalculate_score()
    
    def _recalculate_score(self) -> None:
        """Recalculate health score based on recent history."""
        total = self.recent_successes + self.recent_failures
        if total == 0:
            self.score = 1.0  # New agent, assume healthy
            self.degraded = False
            return
        
        # Simple success ratio with exponential decay for older events
        success_rate = self.recent_successes / total
        self.score = max(0.0, min(1.0, success_rate))
        
        # Mark as degraded if score drops below threshold
        self.degraded = self.score < 0.5
    
    def reset_stats(self) -> None:
        """Reset statistics (e.g., after recovery)."""
        self.recent_successes = 0
        self.recent_failures = 0
        self.score = 1.0
        self.degraded = False
        self.degradation_reason = None


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    
    selected_agent: Optional[Agent]
    reason: str
    alternatives: List[Agent] = field(default_factory=list)
    health_scores: Dict[str, float] = field(default_factory=dict)
    fallback_used: bool = False
    timestamp: float = field(default_factory=time.time)


class WALLogger:
    """
    Write-Ahead Log for routing decisions.
    
    Optional audit trail for routing decisions. Default: OFF.
    Can be enabled via configuration for compliance/debugging.
    
    Safeguards:
    - Configurable (default OFF)
    - Automatic rotation at configurable size
    - Local filesystem only (no network)
    - Deterministic logging
    """
    
    def __init__(
        self,
        enabled: bool = False,
        log_dir: Optional[Path] = None,
        max_size_mb: int = 10,
        auto_rotate: bool = True,
    ):
        self.enabled = enabled
        self.log_dir = log_dir or Path.home() / ".aetherone" / "wal"
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.auto_rotate = auto_rotate
        self.current_log: Optional[Path] = None
        
        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
    
    def log_routing_decision(
        self,
        context: AgentContext,
        decision: RoutingDecision,
    ) -> None:
        """Log a routing decision to WAL."""
        if not self.enabled:
            return
        
        self._rotate_if_needed()
        
        entry = {
            "timestamp": time.time(),
            "request_id": context.request_id,
            "project_path": context.project_path,
            "file_path": context.file_path,
            "selected_agent": decision.selected_agent.name.value if decision.selected_agent else None,
            "reason": decision.reason,
            "fallback_used": decision.fallback_used,
            "health_scores": decision.health_scores,
            "alternatives": [a.name.value for a in decision.alternatives],
        }
        
        try:
            with open(self.current_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write WAL entry: {e}")
    
    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if self.current_log is None:
            self.current_log = self.log_dir / f"routing_{int(time.time())}.jsonl"
            return
        
        if not self.auto_rotate:
            return
        
        try:
            if self.current_log.exists() and self.current_log.stat().st_size > self.max_size_bytes:
                # Rotate: current log becomes archive
                archive_name = self.current_log.stem + f"_archived_{int(time.time())}.jsonl"
                archive_path = self.log_dir / archive_name
                self.current_log.rename(archive_path)
                # Create new log
                self.current_log = self.log_dir / f"routing_{int(time.time())}.jsonl"
                logger.info(f"Rotated WAL log to {archive_path}")
        except Exception as e:
            logger.warning(f"Failed to rotate WAL: {e}")


class AdaptiveHybridMesh:
    """
    Adaptive Hybrid Mesh (AHM) - Primary Routing Brain for Aether-One.
    
    Responsibilities:
    - Route agent requests based on context and agent health
    - Monitor agent health and detect degradation
    - Provide fallback routing when primary agents fail
    - Optional audit logging via WAL (default: OFF)
    - Maintain backward compatibility with legacy mesh API
    
    This is the SINGLE authoritative routing system. No other routing
    logic should exist outside this class.
    """
    
    def __init__(
        self,
        registry: AgentRegistry = None,
        enable_wal: bool = False,
        wal_dir: Optional[Path] = None,
    ):
        """
        Initialize AHM.
        
        Args:
            registry: Agent registry (uses default if None)
            enable_wal: Enable WAL logging (default: False)
            wal_dir: WAL directory (default: ~/.aetherone/wal)
        """
        self.registry = registry or default_agent_registry
        self.health_scores: Dict[str, AgentHealthScore] = {}
        self.wal = WALLogger(enabled=enable_wal, log_dir=wal_dir)
        
        # Initialize health scores for all registered agents
        self._initialize_health_scores()
        
        logger.info(
            f"AHM initialized: registry={len(self.registry.all())} agents, "
            f"WAL={'enabled' if enable_wal else 'disabled'}"
        )
    
    def _initialize_health_scores(self) -> None:
        """Initialize health scores for all registered agents."""
        for agent in self.registry.all():
            if agent.name.value not in self.health_scores:
                self.health_scores[agent.name.value] = AgentHealthScore(
                    agent_name=agent.name.value,
                    score=1.0,
                )
    
    async def route_and_run(
        self,
        ctx: AgentContext,
        agent_filter: Optional[List[Agent]] = None,
    ) -> List[AgentResult]:
        """
        Route request to appropriate agent(s) and execute.
        
        Main routing entry point. Selects best agent(s) based on:
        - Agent can_handle() capability
        - Agent health score
        - Context requirements
        
        Args:
            ctx: Agent context
            agent_filter: Optional list of agents to consider (if None, uses all)
        
        Returns:
            List of agent results
        """
        agents = agent_filter if agent_filter is not None else self.registry.all()
        
        # Filter to capable agents
        capable_agents = [a for a in agents if a.can_handle(ctx)]
        
        if not capable_agents:
            logger.warning(f"No capable agents for context: {ctx.request_id}")
            return []
        
        # Select best agent based on health scores
        decision = self._select_agent(capable_agents, ctx)
        
        # Log decision to WAL
        self.wal.log_routing_decision(ctx, decision)
        
        # Execute selected agent
        results = []
        if decision.selected_agent:
            result = await self._execute_with_health_tracking(
                decision.selected_agent, ctx
            )
            results.append(result)
            
            # If execution failed and we have alternatives, try fallback
            if result.status == "error" and decision.alternatives:
                logger.info(
                    f"Primary agent {decision.selected_agent.name} failed, "
                    f"attempting fallback to {len(decision.alternatives)} alternatives"
                )
                fallback_result = await self._execute_fallback(
                    decision.alternatives, ctx
                )
                if fallback_result:
                    results.append(fallback_result)
        
        return results
    
    def _select_agent(
        self,
        capable_agents: List[Agent],
        ctx: AgentContext,
    ) -> RoutingDecision:
        """
        Select best agent from capable agents based on health scores.
        
        Deterministic selection:
        1. Score agents by health
        2. Select highest scoring healthy agent
        3. Provide degraded agents as alternatives (for fallback)
        """
        if not capable_agents:
            return RoutingDecision(
                selected_agent=None,
                reason="No capable agents available",
            )
        
        # Score all capable agents
        scored_agents: List[Tuple[Agent, float]] = []
        for agent in capable_agents:
            health = self.health_scores.get(
                agent.name.value,
                AgentHealthScore(agent_name=agent.name.value, score=1.0)
            )
            scored_agents.append((agent, health.score))
        
        # Sort by score (highest first) - deterministic tie-breaking by name
        scored_agents.sort(key=lambda x: (x[1], x[0].name.value), reverse=True)
        
        # Select best agent
        best_agent, best_score = scored_agents[0]
        alternatives = [a for a, s in scored_agents[1:] if s >= 0.3]  # Only non-failed alternatives
        
        health_scores = {a.name.value: s for a, s in scored_agents}
        
        reason = f"Selected {best_agent.name.value} with health score {best_score:.2f}"
        if best_score < 0.5:
            reason += " (degraded)"
        
        return RoutingDecision(
            selected_agent=best_agent,
            reason=reason,
            alternatives=alternatives,
            health_scores=health_scores,
            fallback_used=False,
        )
    
    async def _execute_with_health_tracking(
        self,
        agent: Agent,
        ctx: AgentContext,
    ) -> AgentResult:
        """Execute agent and update health score."""
        agent_name = agent.name.value
        
        # Get or create health score
        if agent_name not in self.health_scores:
            self.health_scores[agent_name] = AgentHealthScore(
                agent_name=agent_name,
                score=1.0,
            )
        
        health = self.health_scores[agent_name]
        
        try:
            # Execute agent
            result = await agent.run(ctx)
            
            # Update health based on result
            if result.status == "ok":
                health.update_success()
                logger.debug(f"Agent {agent_name} succeeded, health: {health.score:.2f}")
            else:
                health.update_failure(reason=result.message)
                logger.warning(
                    f"Agent {agent_name} returned non-ok status: {result.status}, "
                    f"health: {health.score:.2f}"
                )
            
            return result
            
        except Exception as e:
            # Update health for exception
            health.update_failure(reason=str(e))
            logger.error(
                f"Agent {agent_name} raised exception: {e}, "
                f"health: {health.score:.2f}"
            )
            
            return AgentResult(
                agent_name=agent.name,
                status="error",
                message=f"Agent execution failed: {e}",
                payload={"exception": str(e)},
            )
    
    async def _execute_fallback(
        self,
        alternatives: List[Agent],
        ctx: AgentContext,
    ) -> Optional[AgentResult]:
        """Execute fallback agents in order until one succeeds."""
        for agent in alternatives:
            logger.info(f"Trying fallback agent: {agent.name.value}")
            result = await self._execute_with_health_tracking(agent, ctx)
            
            if result.status == "ok":
                logger.info(f"Fallback agent {agent.name.value} succeeded")
                result.payload["fallback_used"] = True
                return result
        
        logger.error("All fallback agents failed")
        return None
    
    # --- Legacy mesh API compatibility ---
    
    async def run_internal(self, ctx: AgentContext) -> List[AgentResult]:
        """Run internal agents (legacy mesh API compatibility)."""
        return await self.route_and_run(ctx, agent_filter=self.registry.internal_agents())
    
    async def run_product(self, ctx: AgentContext) -> List[AgentResult]:
        """Run product agents (legacy mesh API compatibility)."""
        return await self.route_and_run(ctx, agent_filter=self.registry.product_agents())
    
    async def run_agent(self, name: AgentName, ctx: AgentContext) -> AgentResult:
        """Run specific agent by name (legacy mesh API compatibility)."""
        agent = self.registry.get(name)
        if not agent:
            return AgentResult(
                agent_name=name,
                status="error",
                message=f"Agent {name} not registered",
            )
        
        return await self._execute_with_health_tracking(agent, ctx)
    
    # --- Health monitoring API ---
    
    def get_agent_health(self, agent_name: str) -> Optional[AgentHealthScore]:
        """Get health score for an agent."""
        return self.health_scores.get(agent_name)
    
    def get_all_health_scores(self) -> Dict[str, AgentHealthScore]:
        """Get all agent health scores."""
        return dict(self.health_scores)
    
    def get_degraded_agents(self) -> List[AgentHealthScore]:
        """Get list of degraded agents."""
        return [h for h in self.health_scores.values() if h.degraded]
    
    def reset_agent_health(self, agent_name: str) -> bool:
        """Reset health score for an agent."""
        if agent_name in self.health_scores:
            self.health_scores[agent_name].reset_stats()
            logger.info(f"Reset health for agent: {agent_name}")
            return True
        return False


# Default AHM instance (WAL disabled by default)
default_ahm = AdaptiveHybridMesh(
    registry=default_agent_registry,
    enable_wal=False,  # Default: OFF (can be enabled via config)
)
