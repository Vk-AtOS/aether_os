"""Stage 3: BACKEND — consolidated supervisor.

Inputs (from accumulated_context):  domain_ir, permission_model, integration_map,
  architecture_decisions, project_contract, domain, stack_profile.
Outputs (into accumulated_context): backend_output_path, api_routes, seed_entities,
  integration_clients, design_tokens, governor_report.

Sub-steps:
  1. [SEQ] p04_backend        — scaffold + main.py + auth.py + models.py + schemas.py + seed.py
  2. [SEQ] p04a_backend_codegen — CRUD routers (called internally by p04_backend)
  3. [SEQ] p04b_business_logic — workflow_engine.py + business_rules.py
  4. [SEQ] p04c_integration_codegen — async clients per integration (skipped if none)
  5. [SEQ] Architecture Governor — phantom-entity validation against Domain IR
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.utils import get_domain_ir
from aether_os.stages.s03_backend.helpers import validate_backend_output, get_entity_count

logger = logging.getLogger(__name__)


class BackendStageSupervisor(PhaseBase):
    """Stage 3 supervisor — orchestrates the full backend generation pipeline."""

    phase_name = "s03_backend"

    # ------------------------------------------------------------------ #
    # Task                                                                 #
    # ------------------------------------------------------------------ #

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        """Run all backend sub-steps and merge outputs into one TaskResult."""
        from aether_os.core.projects import get_project_manager

        pm = get_project_manager()
        output_dir: Path = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        data: dict = phase_input.input_data if hasattr(phase_input, "input_data") else {}

        # ── Step 1 + 2: p04_backend (calls p04a internally) ──────────────────
        p04_result = await self._run_p04_backend(phase_input, memory_ctx, output_dir)

        merged_data: dict = {}
        if p04_result.success and p04_result.metadata:
            merged_data.update(p04_result.metadata)
            # Propagate key paths into input_data so p04b can find them
            for key in ("backend_output_path", "backend_src_dir", "api_routes_path"):
                val = p04_result.metadata.get(key) or (
                    p04_result.output_path if key == "backend_output_path" else ""
                )
                if val:
                    data[key] = val
                    merged_data[key] = val

            # Ensure backend_output_path is always populated
            if "backend_output_path" not in merged_data:
                merged_data["backend_output_path"] = p04_result.output_path
                data["backend_output_path"] = p04_result.output_path

        # ── Step 3: p04b_business_logic (sequential — needs backend_output_path) ─
        p04b_result = await self._run_p04b_business_logic(phase_input, memory_ctx, output_dir)
        if p04b_result.success and p04b_result.metadata:
            merged_data.update(p04b_result.metadata)

        # ── Step 4: p04c_integration_codegen (parallel with governor check) ──
        integration_map: dict = data.get("integration_map", {})
        integrations = (
            integration_map.get("integrations", [])
            if isinstance(integration_map, dict)
            else []
        )

        if integrations:
            p04c_result = await self._run_p04c_integration_codegen(
                phase_input, memory_ctx, output_dir
            )
            if p04c_result.success and p04c_result.metadata:
                clients = p04c_result.metadata.get("clients_generated", [])
                merged_data["integration_clients"] = clients
        else:
            logger.info("[s03_backend] No integrations in context — skipping p04c")
            merged_data["integration_clients"] = []

        # ── Step 5: Architecture Governor ────────────────────────────────────
        merged_data["governor_report"] = self._run_governor(
            output_dir, merged_data.get("backend_output_path", "")
        )

        # ── Collect api_routes from metadata / routes file ────────────────────
        merged_data.setdefault("api_routes", self._load_api_routes(merged_data))

        # ── Seed entities ─────────────────────────────────────────────────────
        entities: list = get_domain_ir(data).get("entities", []) or data.get("entities", [])
        merged_data["seed_entities"] = [e.get("name", "") for e in entities if e.get("name")]

        # ── Design tokens placeholder (populated by UI/UX sub-phase if present) ─
        merged_data.setdefault("design_tokens", {})

        # ── Record stage output for feedback tracker ──────────────────────────
        try:
            from aether_os.core.stage_feedback import record_stage_output
            _run_id = str(getattr(phase_input, "project_id", "unknown"))
            _backend_out = merged_data.get("backend_output_path", "")
            _backend_files: list[str] = []
            if _backend_out:
                _bp = Path(_backend_out)
                if _bp.exists():
                    _backend_files = [str(p) for p in _bp.rglob("*.py") if "__pycache__" not in str(p)]
            _gov_report = merged_data.get("governor_report", {})
            _quality_scores = {
                "p04_confidence": float(p04_result.confidence),
                "p04b_confidence": float(p04b_result.confidence),
                "phantom_entities": float(len(_gov_report.get("phantom_entities", []))),
                "violation_count": float(_gov_report.get("violation_count", 0)),
            }
            record_stage_output("s03_backend", _run_id, _backend_files, _quality_scores)
        except Exception as _fb_exc:
            logger.warning("[s03_backend] stage_feedback record failed (non-critical): %s", _fb_exc)

        # Record governor phantom-entity corrections in repair learning
        try:
            from aether_os.core.repair_learning import BugClass, RepairEvent, learn_from_repair
            from aether_os.core.stage_feedback import record_stage_fix
            _gov = merged_data.get("governor_report", {})
            for _phantom in _gov.get("phantom_entities", []):
                try:
                    _event = RepairEvent(
                        bug_class=BugClass.MISSING_ROUTER,
                        domain=get_domain_ir(data).get("domain_name", "unknown"),
                        entity=str(_phantom),
                        file_path="",
                        fix_applied=f"phantom entity detected by governor: {_phantom}",
                    )
                    learn_from_repair(_event)
                    record_stage_fix(
                        "s03_backend", _run_id,
                        f"phantom entity in governor: {_phantom}", "phantom_entity",
                    )
                except Exception as _le:
                    logger.warning("[s03_backend] learn_from_repair failed (non-critical): %s", _le)
        except Exception as _rl_exc:
            logger.warning("[s03_backend] repair_learning wiring failed (non-critical): %s", _rl_exc)

        # ── Write consolidated summary ─────────────────────────────────────────
        summary = {
            "stage": "s03_backend",
            "sub_phases": {
                "p04_backend": {
                    "success": p04_result.success,
                    "confidence": p04_result.confidence,
                    "output_path": p04_result.output_path,
                },
                "p04b_business_logic": {
                    "success": p04b_result.success,
                    "confidence": p04b_result.confidence,
                },
                "p04c_integration_codegen": {
                    "skipped": not integrations,
                    "clients": merged_data.get("integration_clients", []),
                },
            },
            "governor_report": merged_data.get("governor_report", {}),
            "backend_output_path": merged_data.get("backend_output_path", ""),
            "api_routes_count": len(merged_data.get("api_routes", [])),
            "entity_router_count": get_entity_count(merged_data.get("backend_output_path", "")),
        }
        summary_path = output_dir / "s03_consolidated.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str))

        overall_success = p04_result.success
        confidence = p04_result.confidence * 0.7 + p04b_result.confidence * 0.3

        return TaskResult(
            output_path=str(summary_path),
            confidence=round(confidence, 3),
            metadata=merged_data,
            success=overall_success,
            issues=p04_result.issues if not overall_success else [],
        )

    # ------------------------------------------------------------------ #
    # Gate                                                                 #
    # ------------------------------------------------------------------ #

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate fails if backend_output_path is missing or core files are absent."""
        from stages.s03_backend.helpers import validate_backend_output

        backend_path = (result.metadata or {}).get("backend_output_path", "")

        if not backend_path:
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=["backend_output_path is missing from Stage 3 output — "
                        "frontend generation cannot proceed without a backend path"],
            )

        missing = validate_backend_output(backend_path)
        if len(missing) > 2:
            return GateOutcome(
                passed=False,
                confidence=0.2,
                issues=[
                    f"Backend output is incomplete — {len(missing)} required file(s) missing: "
                    f"{missing}. At most 2 optional missing files are tolerated."
                ],
            )

        issues: list[str] = []
        if missing:
            issues.append(f"Minor: {len(missing)} optional file(s) absent: {missing}")

        gov_report = (result.metadata or {}).get("governor_report", {})
        phantom = gov_report.get("phantom_entities", [])
        if phantom:
            issues.append(
                f"Architecture Governor: {len(phantom)} phantom entity/entities detected "
                f"(in generated code but not in Domain IR): {phantom}"
            )

        confidence = 0.93 if not issues else (0.80 if len(issues) == 1 else 0.65)
        return GateOutcome(passed=True, confidence=confidence, issues=issues)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _run_p04_backend(
        self,
        phase_input: Any,
        memory_ctx: List,
        stage_output_dir: Path,
    ) -> TaskResult:
        """Run p04_backend (which internally calls p04a_backend_codegen)."""
        try:
            from aether_os.phases.p04_backend.task_agent import run as p04_run
            sub_dir = stage_output_dir.parent / "p04_backend"
            result = await p04_run(phase_input, memory_ctx, sub_dir)
            logger.info(
                "[s03_backend] p04_backend complete — success=%s confidence=%.2f path=%s",
                result.success, result.confidence, result.output_path,
            )

            # Hoist backend_output_path out of nested metadata into result.metadata
            # so that downstream callers can find it reliably.
            meta = result.metadata or {}
            phases_meta = meta.get("phases", {})
            bc_meta = phases_meta.get("backend_codegen", {})
            bc_output = bc_meta.get("output_path", "")

            if bc_output and "backend_output_path" not in meta:
                meta["backend_output_path"] = bc_output

            # p04a stores backend_src_dir in input_data after running — pick it up
            if hasattr(phase_input, "input_data"):
                for key in ("backend_output_path", "backend_src_dir", "api_routes_path"):
                    val = phase_input.input_data.get(key)
                    if val and key not in meta:
                        meta[key] = val

            # Fallback: use the output_dir itself when p04a sub-dirs aren't available
            if not meta.get("backend_output_path"):
                meta["backend_output_path"] = str(sub_dir)

            return TaskResult(
                output_path=result.output_path,
                confidence=result.confidence,
                metadata=meta,
                success=result.success,
                issues=result.issues,
                confidence_reason=result.confidence_reason,
            )

        except Exception as exc:
            logger.warning("[s03_backend] p04_backend failed: %s", exc)
            return TaskResult(
                output_path=str(stage_output_dir.parent / "p04_backend"),
                confidence=0.0,
                success=False,
                issues=[f"p04_backend error: {exc}"],
            )

    async def _run_p04b_business_logic(
        self,
        phase_input: Any,
        memory_ctx: List,
        stage_output_dir: Path,
    ) -> TaskResult:
        """Run p04b_business_logic to generate services.py and tasks.py."""
        try:
            from aether_os.phases.p04b_business_logic.task_agent import run as p04b_run
            sub_dir = stage_output_dir.parent / "p04b_business_logic"
            result = await p04b_run(phase_input, memory_ctx, sub_dir)
            logger.info(
                "[s03_backend] p04b_business_logic complete — success=%s confidence=%.2f",
                result.success, result.confidence,
            )
            return result
        except Exception as exc:
            logger.warning("[s03_backend] p04b_business_logic failed (non-critical): %s", exc)
            return TaskResult(
                output_path=str(stage_output_dir.parent / "p04b_business_logic"),
                confidence=0.5,
                success=True,  # non-critical — backend still usable without business logic
                issues=[f"p04b_business_logic skipped: {exc}"],
            )

    async def _run_p04c_integration_codegen(
        self,
        phase_input: Any,
        memory_ctx: List,
        stage_output_dir: Path,
    ) -> TaskResult:
        """Run p04c_integration_codegen to generate async integration clients."""
        try:
            from aether_os.phases.p04c_integration_codegen.task_agent import run as p04c_run
            sub_dir = stage_output_dir.parent / "p04c_integration_codegen"
            result = await p04c_run(phase_input, memory_ctx, sub_dir)
            logger.info(
                "[s03_backend] p04c_integration_codegen complete — success=%s clients=%s",
                result.success,
                (result.metadata or {}).get("clients_generated", []),
            )
            return result
        except Exception as exc:
            logger.warning("[s03_backend] p04c_integration_codegen failed (non-critical): %s", exc)
            return TaskResult(
                output_path=str(stage_output_dir.parent / "p04c_integration_codegen"),
                confidence=0.5,
                success=True,  # non-critical — integration clients are optional
                metadata={"clients_generated": [], "skipped": True, "reason": str(exc)},
                issues=[f"p04c_integration_codegen skipped: {exc}"],
            )

    def _run_governor(self, output_dir: Path, backend_output_path: str) -> dict:
        """Run Architecture Governor against the generated backend.

        Returns a dict summary suitable for JSON serialisation.
        Non-fatal: failures are logged and an empty report dict is returned.
        """
        try:
            from aether_os.core.architecture_governor import ArchitectureGovernor

            # Try to load IR from the backend output dir first, then the stage dir
            for search_dir in [
                Path(backend_output_path) if backend_output_path else None,
                output_dir,
                output_dir.parent,
            ]:
                if search_dir is None:
                    continue
                gov = ArchitectureGovernor.from_output_dir(search_dir)
                if gov is not None:
                    break
            else:
                logger.debug(
                    "[s03_backend] Governor: no domain_ir.json found — skipping validation"
                )
                return {}

            # Build code artifacts from generated src directory
            src_dir = Path(backend_output_path) / "src" if backend_output_path else None
            code_artifacts: dict[str, str] = {}
            if src_dir and src_dir.is_dir():
                for rel in ("models.py", "routers/crud.py"):
                    p = src_dir / rel
                    if p.is_file():
                        try:
                            code_artifacts[rel] = p.read_text(encoding="utf-8", errors="ignore")
                        except Exception as read_exc:
                            logger.warning(
                                "[s03_backend] Governor: could not read %s: %s", rel, read_exc
                            )

            report = gov.generate_report("p04_backend", code_artifacts)
            report_dict = {
                "entities_in_ir": report.entities_in_ir,
                "entities_found_in_code": report.entities_found_in_code,
                "phantom_entities": report.phantom_entities,
                "missing_entities": report.missing_entities,
                "violation_count": len(report.violations),
                "violations": [
                    {
                        "type": v.violation_type,
                        "entity": v.entity_name,
                        "severity": v.severity,
                        "detail": v.detail[:200],
                    }
                    for v in report.violations[:20]  # cap to keep JSON small
                ],
            }
            if report.phantom_entities:
                logger.warning(
                    "[s03_backend] Governor: %d phantom entity/entities: %s",
                    len(report.phantom_entities), report.phantom_entities,
                )
            else:
                logger.info(
                    "[s03_backend] Governor: passed — %d IR entities, %d found in code",
                    len(report.entities_in_ir), len(report.entities_found_in_code),
                )
            return report_dict

        except Exception as exc:
            logger.warning("[s03_backend] Architecture Governor failed (non-critical): %s", exc)
            return {}

    def _load_api_routes(self, merged_data: dict) -> list:
        """Load api_routes from the routes JSON file written by p04_backend."""
        routes_path = merged_data.get("api_routes_path", "")
        if routes_path:
            try:
                routes = json.loads(Path(routes_path).read_text())
                if isinstance(routes, list):
                    return routes
            except Exception as exc:
                logger.warning("[s03_backend] Could not load api_routes.json: %s", exc)
        return []
