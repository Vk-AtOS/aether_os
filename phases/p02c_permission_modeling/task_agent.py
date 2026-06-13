"""P02c Permission Modeling — derive a full ABAC permission model from the domain IR.

Makes one LLM call that outputs a structured JSON permission model:
  {
    "roles": [...],
    "resources": [...],
    "permissions": { "RoleName": { "Resource": ["read", "create", ...] } },
    "row_filters": { "RoleName": "filter expression" },
    "field_masks": { "RoleName": { "Resource": ["field1", ...] } }
  }

The result is stored as permission_model.json and returned in TaskResult.data
so it flows into accumulated_context["permission_model"] for p04a to use.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_DEFAULT_PERMISSION_MODEL = {
    "roles": ["SuperAdmin", "Admin", "Manager", "Staff", "ReadOnly"],
    "resources": [],
    "permissions": {
        "SuperAdmin": {"*": ["*"]},
        "Admin": {},
        "Manager": {},
        "Staff": {},
        "ReadOnly": {},
    },
    "row_filters": {},
    "field_masks": {},
}


def _build_default_model(entities: List[str]) -> dict:
    """Build a sensible default permission model when LLM is unavailable."""
    model = {
        "roles": ["SuperAdmin", "Admin", "Manager", "Staff", "ReadOnly"],
        "resources": entities,
        "permissions": {
            "SuperAdmin": {"*": ["*"]},
            "Admin": {e: ["read", "create", "update", "delete"] for e in entities},
            "Manager": {e: ["read", "create", "update"] for e in entities},
            "Staff": {e: ["read", "create"] for e in entities},
            "ReadOnly": {e: ["read"] for e in entities},
        },
        "row_filters": {
            "Manager": "filter by created_by = current_user.id",
        },
        "field_masks": {},
    }
    return model


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """Generate ABAC permission model via one LLM call."""
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict = getattr(phase_input, "input_data", {}) or {}
    domain = data.get("domain", "general")
    project_name = data.get("project_name", "App")
    raw_input = data.get("raw_input", "")[:3000]

    # Extract entities from domain IR
    entities: List[str] = []
    ir_path = data.get("domain_ir_path", "")
    if ir_path:
        try:
            ir = json.loads(Path(ir_path).read_text())
            entities = [e.get("name", "") for e in ir.get("entities", []) if e.get("name")]
        except Exception as exc:
            logger.warning("p02c: could not load domain IR: %s", exc)

    if not entities:
        arch = data.get("architecture_json", {})
        if isinstance(arch, dict):
            for tbl in arch.get("database_schema", []):
                name = tbl.get("name") or tbl.get("table", "")
                if name:
                    entities.append(name)

    if not entities:
        # No entities available — return a skipped result
        logger.info("p02c: no entities found — skipping permission modeling")
        model = _build_default_model(["User"])
        out_path = output_dir / "permission_model.json"
        out_path.write_text(json.dumps(model, indent=2))
        return TaskResult(
            output_path=str(out_path),
            confidence=0.5,
            metadata={"permission_model": model, "skipped": True, "reason": "no entities in context"},
            success=True,
        )

    permission_model = _build_default_model(entities)

    # ── LLM call ────────────────────────────────────────────────────────────────
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()

        prompt = f"""\
You are a security architect designing an attribute-based access control (ABAC) system.

Domain: {domain}
Project: {project_name}
Description: {raw_input}
Entities: {', '.join(entities)}

Design a complete permission model for this application. Output a JSON object:

{{
  "roles": ["SuperAdmin", "Admin", "Manager", "Staff", "ReadOnly"],
  "resources": {json.dumps(entities)},
  "permissions": {{
    "RoleName": {{
      "ResourceName": ["read", "create", "update", "delete"]
    }}
  }},
  "row_filters": {{
    "RoleName": "human-readable filter description e.g. filter by team_id = current_user.team_id"
  }},
  "field_masks": {{
    "RoleName": {{
      "ResourceName": ["sensitive_field1", "sensitive_field2"]
    }}
  }}
}}

Rules:
- SuperAdmin always gets {{"*": ["*"]}} (all permissions)
- Design roles appropriate for a {domain} application
- Be specific about which roles can do what on each resource
- Add row-level filters where managers/staff should only see their own records
- Add field masks to hide sensitive fields (salary, ssn, password_hash, secret_key) from non-admins
- Return ONLY valid JSON. No markdown, no explanation."""

        result = await llm.call(prompt, task_type="analysis", max_tokens=2000)
        if result:
            # Strip markdown fences
            result = re.sub(r"^```(?:json)?\s*\n?", "", result.strip())
            result = re.sub(r"\n?```\s*$", "", result.strip())
            parsed = json.loads(result)
            # Validate structure
            if isinstance(parsed, dict) and "roles" in parsed and "permissions" in parsed:
                permission_model = parsed
                logger.info("p02c: LLM permission model generated — %d roles, %d resources",
                            len(parsed.get("roles", [])), len(parsed.get("resources", [])))
            else:
                logger.warning("p02c: LLM response missing required keys — using default model")
    except Exception as exc:
        logger.warning("p02c: LLM call failed, using default permission model: %s", exc)

    # Ensure resources list is populated
    if not permission_model.get("resources"):
        permission_model["resources"] = entities

    out_path = output_dir / "permission_model.json"
    out_path.write_text(json.dumps(permission_model, indent=2))
    logger.info("p02c: permission_model.json written to %s", out_path)

    return TaskResult(
        output_path=str(out_path),
        confidence=0.88,
        metadata={
            "permission_model": permission_model,
            "roles_count": len(permission_model.get("roles", [])),
            "resources_count": len(permission_model.get("resources", [])),
        },
        success=True,
    )
