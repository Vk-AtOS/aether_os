"""
P00c Architecture Planner — generates a microservices service map.

Only runs when build_profile.architecture == "microservices". For monolith
builds this phase is skipped gracefully (gate always passes, no output).

Outputs:
  service_map.json — list of services, their languages, ports, DB ownership,
                     communication style (REST/gRPC/event), and message bus config.

factory_pipeline.py reads service_map.json after this phase and stores it in
accumulated_context["service_map"], which go_generator uses to produce N
separate service directories instead of one monolith.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.stack_profiles import get_profile, profile_to_dict
from aether_os.phases.base import TaskResult
from aether_os.phases.p00c_architecture_planner.prompts import SERVICE_MAP_PROMPT
from aether_os.phases.p00c_architecture_planner.helpers import (
    coerce_service_map,
    validate_service_map,
    build_fallback_service_map,
    normalise_service_map,
    FRAMEWORK_FOR_LANG,
)

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    if isinstance(build_profile, str):
        # Older p00 results carried only the profile name; resolve it instead of crashing on .get().
        logger.warning("p00c: build_profile is the name %r, not a dict; resolving it", build_profile)
        build_profile = profile_to_dict(get_profile(build_profile))
    elif not isinstance(build_profile, dict):
        logger.warning("p00c: build_profile is %s, ignoring it", type(build_profile).__name__)
        build_profile = {}
    architecture = build_profile.get("architecture", "monolith")

    # Only produce a service map for microservices builds.
    if architecture != "microservices":
        logger.info("p00c: architecture=%s — skipping service map generation", architecture)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"architecture={architecture}"},
            success=True,
        )

    backend_lang = build_profile.get("backend_lang", "python")
    backend_framework = build_profile.get("backend_framework") or FRAMEWORK_FOR_LANG.get(backend_lang, "fastapi")
    profile_name = build_profile.get("name", "go_microservices")
    performance_tier = build_profile.get("performance_tier", "standard")
    domain = data.get("domain", "general")
    spec_text = data.get("raw_input") or data.get("project_description") or domain

    service_map: Dict[str, Any] = {}

    # Attempt LLM-generated service map
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        prompt = SERVICE_MAP_PROMPT.format(
            spec_text=spec_text[:3000],
            domain=domain,
            profile_name=profile_name,
            backend_lang=backend_lang,
            backend_framework=backend_framework,
            performance_tier=performance_tier,
        )
        raw = coerce_service_map(await llm.call_json(prompt, task_type="analysis"), backend_lang)
        errors = validate_service_map(raw)
        if errors:
            logger.warning("p00c: LLM service_map invalid (%s) — using fallback", errors)
            service_map = build_fallback_service_map(spec_text, domain, backend_lang, backend_framework)
        else:
            service_map = normalise_service_map(raw, backend_lang)
            logger.info(
                "p00c: service_map generated — %d services, bus=%s",
                len(service_map.get("services", [])),
                service_map.get("message_bus", ""),
            )
    except Exception as e:
        logger.warning("p00c: LLM call failed, using fallback service_map: %s", e)
        service_map = build_fallback_service_map(spec_text, domain, backend_lang, backend_framework)

    out_path = output_dir / "service_map.json"
    out_path.write_text(json.dumps(service_map, indent=2))

    return TaskResult(
        output_path=str(out_path),
        confidence=0.0 if service_map.get("_fallback") else 0.9,
        metadata={
            "service_count": len(service_map.get("services", [])),
            "message_bus": service_map.get("message_bus", ""),
            "fallback": bool(service_map.get("_fallback")),
        },
        success=True,
    )
