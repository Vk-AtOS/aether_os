"""
Stage 2: ARCHITECTURE
=====================
PURPOSE: Design the technical architecture. Every sub-step depends on the
         previous one, so all four run sequentially.  The Domain IR produced
         by step 2 (p02b_domain_ir) is the single most important artifact in
         the entire pipeline — every downstream code-generation stage reads it.

INPUTS (accumulated_context / phase_input.input_data keys consumed):
  - requirements        : dict  — structured requirements from Stage 1
  - entities            : list  — entity list from Stage 1
  - domain              : str   — business vertical
  - project_contract    : dict  — binding spec from Stage 1
  - service_map         : dict  — service decomposition from Stage 1 (optional)

OUTPUTS (phase_input.input_data keys written by this stage):
  - architecture_json   : dict  — full architecture document (tech stack, endpoints, DB)
  - architecture_warnings : list — compatibility warnings (e.g. SQLite in multi-tenant)
  - domain_ir           : dict  — entity IR with fields, relationships, indexes
  - domain_ir_path      : str   — path to domain_ir.json on disk
  - permission_model    : dict  — ABAC permission matrix
  - project_scaffold    : str   — path to generated project directory

SUB-STEPS (ALL SEQUENTIAL — each depends on previous):
  1. p02_architecture      — architecture decisions (DB, monolith/microservices, stack)
  2. p02b_domain_ir        — entity IR with fields, relationships, indexes  [CRITICAL]
  3. p02c_permission_modeling — ABAC permission matrix from domain IR
  4. p03_scaffolding       — project directory structure + config files

CRITICAL: Yes (p02b_domain_ir output is used by every downstream stage)
LLM CALLS: ~3 (1 per step that calls the LLM; p03 only validates syntax)
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.orchestrator.clarifying import load_answers

from aether_os.core.errors import PipelineBlockedError
from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.phases.failure_reason import failure_issues

logger = logging.getLogger(__name__)

STAGE_CONTRACT = {
    "stage": "s02_architecture",
    "display_name": "Architecture",
    "critical": True,
    "parallel_substeps": [],
    "sequential_substeps": [
        "p02_architecture",
        "p02b_domain_ir",
        "p02c_permission_modeling",
        "p03_scaffolding",
    ],
    "inputs": ["requirements", "entities", "domain", "project_contract", "service_map"],
    "outputs": [
        "architecture_json",
        "architecture_warnings",
        "domain_ir",
        "domain_ir_path",
        "permission_model",
        "project_scaffold",
    ],
}


class ArchitectureStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 2 (Architecture).

    Runs four legacy phases in strict sequence:
      p02_architecture → p02b_domain_ir → p02c_permission_modeling → p03_scaffolding

    p02b_domain_ir is marked CRITICAL: if it fails the stage returns immediately
    with success=False so the pipeline aborts rather than generating code from
    an incomplete or missing domain model.
    """

    phase_name = "s02_architecture"

    async def run_task(
        self, phase_input: Any, memory_ctx: List[Dict]
    ) -> TaskResult:
        from aether_os.core.projects import get_project_manager

        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        issues: List[str] = []

        # Answers to this run's clarifying questions (POST .../clarifying-answers) go into the
        # context before p02b runs: it feeds them to the extraction and applies them to the IR.
        phase_input.input_data["clarifying_answers"] = load_answers(phase_input.run_id)

        # ── Step 1: Architecture decisions ────────────────────────────────────
        # Writes architecture.json; populates architecture_warnings, decisions,
        # and tech_stack choices into accumulated_context.
        arch_result = await self._run_sub_phase(
            "p02_architecture", phase_input, memory_ctx, pm, critical=False
        )
        if isinstance(arch_result, Exception):
            logger.warning("s02: p02_architecture failed (non-critical): %s", arch_result)
            issues.append(f"p02_architecture failed: {arch_result}")
        elif isinstance(arch_result, TaskResult):
            # Always propagate architecture_warnings even when the step succeeded
            # with a fallback, so the gate can surface them to the operator.
            _arch_warnings = phase_input.input_data.get("architecture_warnings", [])
            if _arch_warnings:
                issues.extend(_arch_warnings)
            # Store the architecture output path so p02b can load architecture.json
            if arch_result.output_path:
                phase_input.input_data["p02_architecture_path"] = arch_result.output_path
            # Also load the JSON document into context so p03 can read tech_stack.
            _arch_json_path = Path(arch_result.output_path) if arch_result.output_path else None
            if _arch_json_path and _arch_json_path.is_file():
                try:
                    phase_input.input_data["architecture_json"] = json.loads(
                        _arch_json_path.read_text()
                    )
                except Exception as exc:
                    logger.warning("s02: could not parse architecture.json: %s", exc)

        # ── Step 2: Domain IR extraction (CRITICAL) ──────────────────────────
        # Reads architecture.json + requirements; writes domain_ir.json.
        # Every downstream code-generation stage (p04a, p05) consumes this file.
        ir_result = await self._run_sub_phase(
            "p02b_domain_ir", phase_input, memory_ctx, pm
        )
        if isinstance(ir_result, Exception):
            logger.error("s02 CRITICAL: p02b_domain_ir raised: %s", ir_result)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=issues + [f"p02b_domain_ir failed: {ir_result}"],
                metadata=dict(phase_input.input_data),
            )
        if not ir_result.success:
            logger.error(
                "s02 CRITICAL: p02b_domain_ir returned success=False: %s",
                ir_result.issues,
            )
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=issues + (ir_result.issues or ["domain IR extraction failed"]),
                metadata=dict(phase_input.input_data),
            )
        # Expose domain_ir_path so p02c and downstream phases can locate the file.
        if ir_result.output_path:
            phase_input.input_data["domain_ir_path"] = ir_result.output_path
        if ir_result.metadata:
            # Bubble up entity/field counts and the domain validation report.
            for key in ("entity_count", "field_count", "relationship_count",
                        "metric_count", "domain_validation"):
                if key in ir_result.metadata:
                    phase_input.input_data[key] = ir_result.metadata[key]

        # Clarifying questions: the domain model lists every field it could not
        # infer. Carry the full list (not just p02b's count) in the stage metadata,
        # and write it to this stage's summary file, which the run-detail endpoint
        # serves as phases.s02_architecture.output.
        questions = self._read_clarifying_questions(ir_result.output_path)
        phase_input.input_data["clarifying_questions"] = questions
        phase_input.input_data["has_questions"] = bool(questions)
        (output_dir / f"{self.phase_name}.json").write_text(json.dumps({
            "clarifying_questions": questions,
            "clarifying_answers": phase_input.input_data.get("clarifying_answers") or {},
            "has_questions": bool(questions),
            **{k: ir_result.metadata[k] for k in ("entity_count", "field_count")
               if k in (ir_result.metadata or {})},
        }, indent=2))

        # ── Step 3: Permission modeling (non-critical) ────────────────────────
        perm_result = await self._run_sub_phase(
            "p02c_permission_modeling", phase_input, memory_ctx, pm, critical=False
        )
        if isinstance(perm_result, Exception):
            logger.warning(
                "s02: p02c_permission_modeling failed (non-critical): %s", perm_result
            )
            issues.append(f"p02c_permission_modeling failed: {perm_result}")
        elif isinstance(perm_result, TaskResult) and perm_result.metadata:
            permission_model = perm_result.metadata.get("permission_model")
            if permission_model:
                phase_input.input_data["permission_model"] = permission_model

        # ── Step 4: Scaffolding (non-critical) ───────────────────────────────
        scaf_result = await self._run_sub_phase(
            "p03_scaffolding", phase_input, memory_ctx, pm, critical=False
        )
        if isinstance(scaf_result, Exception):
            logger.warning(
                "s02: p03_scaffolding failed (non-critical): %s", scaf_result
            )
            issues.append(f"p03_scaffolding failed: {scaf_result}")
        elif isinstance(scaf_result, TaskResult):
            if scaf_result.output_path:
                phase_input.input_data["project_scaffold"] = scaf_result.output_path
            if scaf_result.issues:
                issues.extend(scaf_result.issues)

        # Derive overall confidence: IR confidence dominates because it's the
        # artifact that most affects downstream quality.
        confidence = ir_result.confidence if isinstance(ir_result, TaskResult) else 0.6

        return TaskResult(
            output_path=str(output_dir),
            confidence=confidence,
            success=True,
            issues=issues,
            metadata=dict(phase_input.input_data),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _read_clarifying_questions(ir_path: str) -> List[Dict[str, Any]]:
        """The clarifying questions saved in domain_ir.json ([] if there are none)."""
        try:
            return list(json.loads(Path(ir_path).read_text()).get("clarifying_questions") or [])
        except Exception as exc:
            logger.warning("s02: could not read clarifying questions from %s: %s", ir_path, exc)
            return []

    async def _run_sub_phase(
        self, phase_name: str, phase_input: Any, memory_ctx: list, pm,
        critical: bool = True,
    ) -> TaskResult:
        """Import and call a legacy phase's task_agent.run().

        critical=False returns the exception instead of raising it, so the caller's
        "non-critical" handling runs. PipelineBlockedError (a gate denial) always
        propagates: a denied gate must stop the run.
        """
        try:
            mod = importlib.import_module(
                f"aether_os.phases.{phase_name}.task_agent"
            )
            output_dir = pm.get_output_dir(phase_input.project_id, phase_name)
            output_dir.mkdir(parents=True, exist_ok=True)
            return await mod.run(phase_input, memory_ctx, output_dir)
        except PipelineBlockedError:
            raise
        except Exception as e:
            logger.warning("s02: sub-phase %s raised: %s", phase_name, e)
            if critical:
                raise
            return e

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        if not result.success:
            return GateOutcome(
                passed=False,
                issues=result.issues or failure_issues("s02_architecture", "architecture", result),
            )
        # domain_ir_path must exist and the file must be non-empty.
        ir_path_str = phase_input.input_data.get("domain_ir_path", "")
        if not ir_path_str:
            return GateOutcome(
                passed=False,
                issues=["domain_ir_path not set — p02b_domain_ir may not have run"],
            )
        ir_path = Path(ir_path_str)
        if not ir_path.exists() or ir_path.stat().st_size == 0:
            return GateOutcome(
                passed=False,
                issues=[f"domain_ir.json missing or empty at {ir_path}"],
            )
        # Verify at least one entity was extracted.
        try:
            ir_data = json.loads(ir_path.read_text())
            entities = ir_data.get("entities", [])
            if not entities:
                return GateOutcome(
                    passed=False,
                    issues=["domain_ir.json contains no entities"],
                )
        except Exception as exc:
            return GateOutcome(
                passed=False,
                issues=[f"domain_ir.json could not be parsed: {exc}"],
            )
        gate_issues = []
        arch_warnings = phase_input.input_data.get("architecture_warnings", [])
        if arch_warnings:
            # Warnings don't block the gate — they are surfaced as gate.issues
            # so the orchestrator can log and display them without aborting.
            gate_issues.extend(arch_warnings)
        return GateOutcome(
            passed=True,
            confidence=result.confidence,
            issues=gate_issues,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def _clone_phase_input(phase_input: Any) -> Any:
    """Shallow-copy phase_input with a deep-copy of input_data."""
    cloned = copy.copy(phase_input)
    cloned.input_data = copy.deepcopy(phase_input.input_data)
    return cloned
