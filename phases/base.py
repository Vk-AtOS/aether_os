"""AetherOS — Shared base classes for the 4-agent phase pattern."""
from __future__ import annotations
import asyncio
import httpx
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.identity.zero_trust import verify_ticket
from aether_os.core.memory.fingerprinter import fingerprint
from aether_os.core.memory.store import MemoryRecord, get_memory_store
from aether_os.core.memory.vector_store import ChromaProjectMemory
from aether_os.orchestrator.bus import get_bus
from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    output_path: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    success: bool = True
    escalated: bool = False  # True when all retries failed and a human ticket was filed
    confidence_reason: str = ""  # Human-readable explanation of confidence score


@dataclass
class GateOutcome:
    passed: bool
    issues: List[str] = field(default_factory=list)
    confidence: float = 1.0


class PhaseBase:
    """
    Base class for the 4-agent phase pattern.
    Subclasses implement: run_task(), validate_gate(), phase_name.
    supervisor_agent orchestrates: memory → task → gate → retry → escalate → comms.
    """
    phase_name: str = "base"
    max_retries: int = 3

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"aether_os.phases.{self.phase_name}")

    # ── Memory Agent ─────────────────────────────────────────────────────────

    async def memory_before(self, input_hash: str, phase: str,
                            limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant memories before the task."""
        try:
            records = await get_memory_store().retrieve(input_hash, k=limit)
            return [
                {"output_text": r.output_text, "confidence": r.confidence,
                 "success_count": r.success_count}
                for r in records
            ]
        except Exception as e:
            self.logger.debug("Memory retrieve skipped: %s", e)
            return []

    async def memory_after(self, phase: str, input_hash: str, output_path: str,
                           confidence: float, domain: str = "general",
                           tags: Optional[List[str]] = None,
                           result_metadata: Optional[Dict] = None) -> None:
        """Store successful outcome with rich metadata for future cross-run injection."""
        try:

            # Build a meaningful summary that downstream phases can actually use
            meta = result_metadata or {}
            project = meta.get("project_name", "")
            entities = meta.get("entities_count", meta.get("entities", ""))
            stack = meta.get("tech_stack", "")
            generated_via = meta.get("generated_via", "")
            files_written = meta.get("files_written", "")

            parts = [f"[{phase}]"]
            if project:
                parts.append(f"project={project}")
            if domain and domain != "general":
                parts.append(f"domain={domain}")
            if entities:
                parts.append(f"entities={entities}")
            if stack:
                parts.append(f"stack={stack}")
            if generated_via:
                parts.append(f"via={generated_via}")
            if files_written:
                parts.append(f"files={files_written}")
            parts.append(f"confidence={confidence:.2f}")

            summary = " | ".join(parts)

            # Also store the first 800 chars of meaningful metadata as JSON
            if meta:
                meta_str = json.dumps({k: v for k, v in meta.items()
                                        if isinstance(v, (str, int, float, bool, list))
                                        and k not in ("files", "files_written")}, ensure_ascii=False)
                summary += f"\nMeta: {meta_str[:600]}"

            await get_memory_store().store(MemoryRecord(
                input_hash=input_hash,
                input_text=f"[{phase}] {domain}",
                output_text=summary,
                task_type=phase,
                metadata={"domain": domain, "confidence": confidence},
                success_count=1,
            ))
            # Also populate ChromaDB for semantic search across runs
            try:
                chroma = ChromaProjectMemory.get_instance()
                if chroma.available:
                    project_name_val = (result_metadata or {}).get("project_name", "")
                    run_id_val = (result_metadata or {}).get("run_id", input_hash[:8])
                    chroma.store(
                        run_id=run_id_val,
                        org_id=domain,  # use domain as org context for phase-level storage
                        raw_input=summary,
                        domain=domain,
                        project_name=project_name_val,
                        winning_approach=summary[:500],
                    )
            except Exception as exc:
                self.logger.debug("Memory store (inner) failed (non-fatal): %s", exc)
        except Exception as e:
            self.logger.debug("Memory store skipped: %s", e)

    # ── Communication Agent ──────────────────────────────────────────────────

    async def communicate(self, run_id: str, phase: str, status: str,
                          output_path: str, confidence: float,
                          issues: List[str], next_phase: Optional[str] = None,
                          upstream_route: Optional[str] = None,
                          artifacts: Optional[Dict] = None,
                          failure_context: Optional[Dict] = None,
                          client_id: Optional[str] = None,
                          whatsapp_msg: Optional[str] = None) -> None:
        """Post PhaseResult to message bus and optionally send WhatsApp."""
        result = PhaseResult(
            run_id=run_id,
            phase=phase,
            status=status,  # type: ignore[arg-type]
            output_path=output_path,
            confidence=confidence,
            issues=issues,
            next_phase=next_phase,
            upstream_route=upstream_route,
            failure_context=failure_context,
            artifacts=artifacts or {},
        )
        msg = PhaseMessage(from_phase=phase, to_phase=next_phase, result=result)
        await get_bus(run_id).publish(msg)

        if whatsapp_msg and client_id:
            await self._send_whatsapp(client_id, whatsapp_msg)

    async def _send_whatsapp(self, client_id: str, message: str) -> None:
        """Send WhatsApp message via WAHA HTTP API."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    os.getenv("WAHA_URL", "http://localhost:3000") + "/api/sendText",
                    json={"chatId": f"{client_id}@c.us",
                          "text": message, "session": "default"},
                )
        except Exception as e:
            self.logger.debug("WhatsApp send skipped (WAHA not running): %s", e)

    # ── Supervisor Agent ─────────────────────────────────────────────────────

    async def run(self, phase_input: Any) -> TaskResult:
        """
        Supervisor logic: memory → task → gate → retry/escalate → communicate.
        """
        # Verify the zero-trust ticket issued by the pipeline orchestrator.
        # A missing ticket is warned (not fatal) so phases still run during
        # unit tests and dev runs where AETHER_ONE_ZT_SECRET may not be set.
        _zt_ticket = (phase_input.input_data or {}).get("_zt_ticket")
        if _zt_ticket:
            try:
                verify_ticket(
                    _zt_ticket,
                    project_path=phase_input.run_id,
                    resource_path=phase_input.output_dir,
                    action=self.phase_name,
                )
            except Exception as _zt_exc:
                self.logger.warning(
                    "[%s] Zero-trust ticket verification failed: %s",
                    self.phase_name, _zt_exc,
                )
        else:
            self.logger.debug(
                "[%s] No zero-trust ticket present — running without ZT enforcement",
                self.phase_name,
            )

        input_hash = fingerprint(str(phase_input.input_data))
        memory_ctx = await self.memory_before(input_hash, self.phase_name)

        attempt = 0
        last_error = ""
        while attempt < self.max_retries:
            attempt += 1
            try:
                result = await self.run_task(phase_input, memory_ctx)
                gate = await self.validate_gate(result, phase_input)

                if gate.passed:
                    # Persist gate result to disk for Phase Detail view
                    try:
                        _op = Path(result.output_path)
                        _gate_dir = _op if _op.is_dir() else _op.parent
                        if _gate_dir.exists():
                            (_gate_dir / "gate_result.json").write_text(json.dumps({
                                "passed": gate.passed,
                                "confidence": gate.confidence,
                                "issues": gate.issues,
                            }, indent=2))
                    except Exception as exc:
                        self.logger.debug("gate_result.json write failed (non-fatal): %s", exc)
                    await self.memory_after(
                        self.phase_name, input_hash, result.output_path,
                        result.confidence, getattr(phase_input, "domain", "general"),
                        result_metadata=result.metadata,
                    )
                    await self.communicate(
                        run_id=phase_input.run_id,
                        phase=self.phase_name,
                        status="passed",
                        output_path=result.output_path,
                        confidence=result.confidence,
                        issues=gate.issues,
                        artifacts=result.metadata,
                        client_id=getattr(phase_input, "client_id", None),
                    )
                    return result
                else:
                    last_error = "; ".join(gate.issues)
                    self.logger.warning(
                        "[%s] Gate fail attempt %d/%d: %s",
                        self.phase_name, attempt, self.max_retries, last_error,
                    )
                    memory_ctx = [{"failure": last_error}] + memory_ctx

            except Exception as e:
                last_error = str(e)
                self.logger.error("[%s] Task error attempt %d: %s",
                                  self.phase_name, attempt, e)

        # All retries exhausted — escalate and signal the pipeline to block
        await self._escalate(phase_input, last_error)
        return TaskResult(
            output_path="",
            confidence=0.0,
            success=False,
            escalated=True,
            issues=[last_error],
        )

    async def _escalate(self, phase_input: Any, reason: str) -> None:
        """Signal the pipeline that human approval is required.

        Publishes an "escalated" phase message to the bus so SSE clients see it
        immediately. The pipeline loop in factory_pipeline.py detects the
        "escalated" status on the returned TaskResult and calls
        _await_human_approval() which registers the Decision and blocks until
        an operator resolves it via POST /decisions/{id}/approve.
        """
        self.logger.warning("[%s] All retries exhausted — escalating to human. reason=%s",
                            self.phase_name, reason)
        await self.communicate(
            run_id=phase_input.run_id,
            phase=self.phase_name,
            status="escalated",
            output_path="",
            confidence=0.0,
            issues=[reason],
            failure_context={"reason": reason, "phase": self.phase_name},
            client_id=getattr(phase_input, "client_id", None),
        )

    # ── Subclass interface ───────────────────────────────────────────────────

    async def run_task(self, phase_input: Any,
                       memory_ctx: List[Dict]) -> TaskResult:
        raise NotImplementedError

    async def validate_gate(self, result: TaskResult,
                            phase_input: Any) -> GateOutcome:
        return GateOutcome(passed=result.success, issues=result.issues)
