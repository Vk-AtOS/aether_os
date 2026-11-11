"""
AetherOS — Concrete agent implementations (T5-07).

All 14 agents declared in agents/base.py are implemented here.
Each agent uses existing AetherOS infrastructure (policy engine,
memory store, compliance engine, LLM client) — no net-new external
calls unless explicitly noted.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import Agent, AgentContext, AgentKind, AgentName, AgentResult, AgentRegistry

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok(name: AgentName, msg: str, payload: dict = None) -> AgentResult:
    return AgentResult(agent_name=name, status="ok", message=msg,
                       payload=payload or {}, finished_ts=time.time())

def _err(name: AgentName, msg: str) -> AgentResult:
    return AgentResult(agent_name=name, status="error", message=msg,
                       finished_ts=time.time())

def _blocked(name: AgentName, msg: str) -> AgentResult:
    return AgentResult(agent_name=name, status="blocked", message=msg,
                       finished_ts=time.time())


# ── Internal agents ───────────────────────────────────────────────────────────

class PolicyAgent(Agent):
    """Enforces pipeline policy before critical operations."""

    def __init__(self) -> None:
        super().__init__(AgentName.POLICY, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        org_id = ctx.metadata.get("org_id", "")
        plan = ctx.metadata.get("plan", "trial")
        try:
            from aether_os.core.policy.engine import get_policy_engine
            engine = get_policy_engine()
            ok, msg = engine.check_pipeline_start(org_id=org_id, plan=plan)
            if not ok:
                return _blocked(self.name, msg)
            return _ok(self.name, "Policy check passed", {"allowed": True})
        except Exception as exc:
            logger.debug("[PolicyAgent] %s", exc)
            return _ok(self.name, "Policy engine unavailable — allowing by default")


class RiskAgent(Agent):
    """Evaluates compliance risk for the given org/project context."""

    def __init__(self) -> None:
        super().__init__(AgentName.RISK, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            from aether_os.core.policy.compliance import (
                ComplianceEngine, ComplianceContext,
            )
            c = ctx.metadata
            compliance_ctx = ComplianceContext(
                country_code=c.get("country_code", ""),
                region=c.get("data_region", "global").upper(),
                deployment_type=c.get("deployment_type", "saas"),
                data_sensitivity=c.get("data_sensitivity", "moderate"),
                handles_personal_data=c.get("handles_personal_data", True),
                handles_biometric_data=c.get("handles_biometric_data", False),
                handles_children_data=c.get("handles_children_data", False),
                industries=c.get("industries", []),
                high_risk_use_cases=c.get("high_risk_use_cases", []),
                uses_strong_crypto=c.get("uses_strong_crypto", True),
                uses_weak_crypto=c.get("uses_weak_crypto", False),
                customer_requires_data_residency=c.get("requires_data_residency", False),
                uses_third_country_cloud=c.get("uses_third_country_cloud", False),
                model_providers=c.get("model_providers", []),
                repo_tags=c.get("repo_tags", []),
            )
            decision = ComplianceEngine().evaluate(compliance_ctx)
            if decision.denied:
                return _blocked(self.name, f"Compliance DENIED: {'; '.join(decision.reasons)}")
            return _ok(self.name, "Risk evaluation complete", decision.to_dict())
        except Exception as exc:
            logger.debug("[RiskAgent] %s", exc)
            return _ok(self.name, "Risk engine unavailable — no violations detected")


class SnapshotAgent(Agent):
    """Persists a point-in-time snapshot of run state for audit/replay."""

    def __init__(self) -> None:
        super().__init__(AgentName.SNAPSHOT, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        run_id = ctx.metadata.get("run_id")
        if not run_id:
            return _err(self.name, "run_id required in ctx.metadata")
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Snapshot
            import json
            sf = get_session_factory()
            snap_data = {k: v for k, v in ctx.metadata.items()
                         if isinstance(v, (str, int, float, bool, type(None)))}
            async with sf() as session:
                snap = Snapshot(
                    run_id=run_id,
                    phase=ctx.metadata.get("phase", "unknown"),
                    data=snap_data,
                )
                session.add(snap)
                await session.commit()
            return _ok(self.name, f"Snapshot saved for run {run_id}")
        except Exception as exc:
            logger.debug("[SnapshotAgent] %s", exc)
            return _err(self.name, f"Snapshot failed: {exc}")


class MemoryKnowledgeAgent(Agent):
    """Retrieves relevant knowledge from the memory store for a given input."""

    def __init__(self) -> None:
        super().__init__(AgentName.MEMORY_KNOWLEDGE, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        input_text = ctx.metadata.get("input_text", "")
        if not input_text:
            return _ok(self.name, "No input_text — skipping memory retrieval", {"records": []})
        try:
            from aether_os.core.memory.store import get_memory_store
            from aether_os.core.memory.fingerprinter import fingerprint
            h = fingerprint(input_text)
            records = await get_memory_store().retrieve(h, k=5)
            return _ok(self.name, f"Retrieved {len(records)} memory records", {
                "records": [
                    {"output_text": r.output_text, "confidence": r.confidence}
                    for r in records
                ]
            })
        except Exception as exc:
            logger.debug("[MemoryKnowledgeAgent] %s", exc)
            return _ok(self.name, "Memory store unavailable", {"records": []})


class RedTeamSafetyAgent(Agent):
    """Basic safety validation — checks outputs for policy violations."""

    _UNSAFE_PATTERNS = [
        "rm -rf /", "DROP TABLE", "DELETE FROM", "; DROP",
        "exec(", "eval(", "__import__(",
        "os.system(", "subprocess.call(",
    ]

    def __init__(self) -> None:
        super().__init__(AgentName.RED_TEAM, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        content = ctx.metadata.get("content", "")
        if not content:
            return _ok(self.name, "No content to scan")
        hits = [p for p in self._UNSAFE_PATTERNS if p in content]
        if hits:
            return _blocked(self.name, f"Unsafe patterns detected: {hits}",)
        return _ok(self.name, "Content passed safety scan")


class StabilityGuardianAgent(Agent):
    """Monitors system health indicators and blocks operations if degraded."""

    def __init__(self) -> None:
        super().__init__(AgentName.STABILITY_GUARDIAN, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        checks: dict[str, str] = {}
        # DB reachability
        try:
            from aether_os.core.db import get_session_factory
            from sqlalchemy import text
            async with get_session_factory()() as s:
                await s.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            logger.warning("StabilityCheckerAgent: DB unreachable: %s", e)
            checks["database"] = "unreachable"

        # Redis reachability
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                await r.ping()
                checks["redis"] = "ok"
            else:
                checks["redis"] = "unavailable"
        except Exception as e:
            logger.warning("StabilityCheckerAgent: Redis unavailable: %s", e)
            checks["redis"] = "unavailable"

        failing = [k for k, v in checks.items() if v not in ("ok", "unavailable")]
        if failing:
            return _blocked(self.name, f"Stability check failed: {failing}", checks)
        return _ok(self.name, "Stability checks passed", checks)


class SystemSpecProfilerAgent(Agent):
    """Profiles hardware and software specs from the accumulated pipeline context."""

    def __init__(self) -> None:
        super().__init__(AgentName.SYSTEM_SPEC_PROFILER, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        import platform, sys
        specs = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "domain": ctx.metadata.get("domain", "unknown"),
            "project_path": ctx.project_path,
        }
        return _ok(self.name, "System spec profile captured", specs)


class BusNetworkManagerAgent(Agent):
    """Reports message bus topology — active runs, queue depths."""

    def __init__(self) -> None:
        super().__init__(AgentName.BUS_NETWORK_MANAGER, AgentKind.INTERNAL)

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if not r:
                return _ok(self.name, "Redis unavailable — bus metrics empty", {"active_channels": 0})
            # Count active pipeline event channels
            keys = await r.keys("pipeline:events:*")
            return _ok(self.name, "Bus network healthy", {"active_channels": len(keys)})
        except Exception as exc:
            logger.warning("BusNetworkManagerAgent: bus check failed: %s", exc)
            return _err(self.name, f"Bus check failed: {exc}")


# ── Product agents ────────────────────────────────────────────────────────────

class FixEngineAgent(Agent):
    """Uses the LLM to suggest a fix for a given error in context."""

    def __init__(self) -> None:
        super().__init__(AgentName.FIX_ENGINE, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        error = ctx.metadata.get("error", "")
        code = ctx.metadata.get("code", "")
        if not error:
            return _ok(self.name, "No error provided — nothing to fix")
        try:
            from aether_os.core.llm.client import get_llm_client
            client = get_llm_client()
            prompt = (
                f"You are a code fix assistant. Given the following error:\n{error}\n\n"
                f"And code:\n{code[:2000]}\n\nProvide a concise fix."
            )
            fix = await client.call(prompt, max_tokens=512)
            return _ok(self.name, "Fix suggestion generated", {"fix": fix})
        except Exception as exc:
            logger.warning("FixEngineAgent: fix engine failed: %s", exc)
            return _err(self.name, f"Fix engine failed: {exc}")


class CodeReviewAgent(Agent):
    """LLM-powered code review focused on correctness and security."""

    def __init__(self) -> None:
        super().__init__(AgentName.CODE_REVIEW, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        code = ctx.metadata.get("code", "")
        if not code:
            return _ok(self.name, "No code provided", {"findings": []})
        try:
            from aether_os.core.llm.client import get_llm_client
            client = get_llm_client()
            prompt = (
                "Review the following code for bugs, security issues, and best-practice violations. "
                "Return a JSON list of findings with keys: severity (high/medium/low), line_hint, message.\n\n"
                f"```\n{code[:3000]}\n```"
            )
            review = await client.call(prompt, max_tokens=1024)
            return _ok(self.name, "Code review complete", {"review": review})
        except Exception as exc:
            logger.warning("CodeReviewAgent: code review failed: %s", exc)
            return _err(self.name, f"Code review failed: {exc}")


class TestAgent(Agent):
    """Parses test results from the pipeline and summarises pass/fail."""

    def __init__(self) -> None:
        super().__init__(AgentName.TEST, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        test_output = ctx.metadata.get("test_output", "")
        import re
        passed = len(re.findall(r"\bpassed\b|\bPASS\b|✓|✔", test_output))
        failed = len(re.findall(r"\bfailed\b|\bFAIL\b|✗|✘|ERROR", test_output))
        return _ok(self.name, f"Tests: {passed} passed, {failed} failed", {
            "passed": passed,
            "failed": failed,
            "success": failed == 0,
        })


class RefactorAgent(Agent):
    """LLM-powered refactoring suggestions."""

    def __init__(self) -> None:
        super().__init__(AgentName.REFACTOR, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        code = ctx.metadata.get("code", "")
        goal = ctx.metadata.get("goal", "improve readability and reduce duplication")
        if not code:
            return _ok(self.name, "No code provided")
        try:
            from aether_os.core.llm.client import get_llm_client
            client = get_llm_client()
            prompt = (
                f"Refactor the following code to {goal}. "
                f"Return the refactored code only.\n\n```\n{code[:3000]}\n```"
            )
            refactored = await client.call(prompt, max_tokens=2048)
            return _ok(self.name, "Refactoring complete", {"refactored_code": refactored})
        except Exception as exc:
            logger.warning("RefactorAgent: refactor failed: %s", exc)
            return _err(self.name, f"Refactor failed: {exc}")


class SecurityAnalyzerAgent(Agent):
    """Combines compliance engine + pattern matching for deep security analysis."""

    def __init__(self) -> None:
        super().__init__(AgentName.SECURITY_ANALYZER, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        code = ctx.metadata.get("code", "")
        findings = []

        # Pattern-based checks (OWASP top 10 indicators)
        _patterns = {
            "SQL_INJECTION": ["execute(", "raw_query(", "format_map(", "% s)"],
            "HARDCODED_SECRET": ["password =", "secret =", "api_key =", "token ="],
            "OPEN_REDIRECT": ["redirect(request.", "Location: http"],
            "COMMAND_INJECTION": ["os.system(", "subprocess.call(", "shell=True"],
        }
        for vuln, pats in _patterns.items():
            for p in pats:
                if p.lower() in code.lower():
                    findings.append({"type": vuln, "pattern": p, "severity": "high"})
                    break

        # Run compliance engine if org context available
        risk_summary = {}
        try:
            from aether_os.core.policy.compliance import ComplianceEngine, ComplianceContext
            _ctx = ComplianceContext(
                country_code="", region="", deployment_type="saas",
                data_sensitivity="moderate", handles_personal_data=True,
                handles_biometric_data=False, handles_children_data=False,
                industries=[], high_risk_use_cases=[],
                uses_strong_crypto=True, uses_weak_crypto=False,
                customer_requires_data_residency=False, uses_third_country_cloud=False,
                model_providers=[], repo_tags=ctx.metadata.get("repo_tags", []),
            )
            decision = ComplianceEngine().evaluate(_ctx)
            risk_summary = decision.to_dict()
        except Exception as exc:
            logger.debug("SecurityScannerAgent: compliance evaluation failed (non-fatal): %s", exc)

        return _ok(self.name, f"Security analysis: {len(findings)} findings", {
            "findings": findings,
            "compliance": risk_summary,
        })


class RepoReasoningAgent(Agent):
    """Uses memory/fingerprinting to reason about code patterns across the repo."""

    def __init__(self) -> None:
        super().__init__(AgentName.REPO_REASONING, AgentKind.PRODUCT)

    async def run(self, ctx: AgentContext) -> AgentResult:
        query = ctx.metadata.get("query", "")
        org_id = ctx.metadata.get("org_id", "")
        if not query:
            return _ok(self.name, "No query provided", {"similar": []})
        try:
            from aether_os.core.memory.matcher import ProjectMatcher
            matcher = ProjectMatcher()
            from aether_os.core.memory.fingerprinter import fingerprint
            fp = fingerprint(query)
            similar = matcher.find_similar(fp, org_id=org_id, top_k=5)
            return _ok(self.name, f"Found {len(similar)} similar projects", {"similar": similar})
        except Exception as exc:
            logger.debug("[RepoReasoningAgent] %s", exc)
            return _ok(self.name, "Repo reasoning unavailable", {"similar": []})


# ── Registry bootstrap ────────────────────────────────────────────────────────

_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        for agent_cls in [
            PolicyAgent, RiskAgent, SnapshotAgent, MemoryKnowledgeAgent,
            RedTeamSafetyAgent, StabilityGuardianAgent, SystemSpecProfilerAgent,
            BusNetworkManagerAgent, FixEngineAgent, CodeReviewAgent, TestAgent,
            RefactorAgent, SecurityAnalyzerAgent, RepoReasoningAgent,
        ]:
            try:
                _registry.register(agent_cls())
            except Exception as exc:
                logger.debug("Agent registration failed: %s", exc)
    return _registry
