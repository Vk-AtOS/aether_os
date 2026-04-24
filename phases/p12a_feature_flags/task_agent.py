"""P12a Task Agent — wire Unleash feature flags."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_dir = Path(data.get("project_dir", str(output_dir)))
    requirements_doc = data.get("requirements_doc", "")
    llm = get_llm_client()

    # docker-compose.unleash.yml
    unleash_compose = """version: '3.8'
services:
  unleash:
    image: unleashorg/unleash-server:latest
    environment:
      - DATABASE_URL=postgres://unleash:unleash@unleash-db/unleash
      - INIT_ADMIN_API_TOKENS=default:development.unleash-insecure-api-token
    ports: ["4242:4242"]
    depends_on: [unleash-db]
  unleash-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: unleash
      POSTGRES_PASSWORD: unleash
      POSTGRES_DB: unleash
"""
    (project_dir / "docker-compose.unleash.yml").write_text(unleash_compose)

    # Generate 3 feature flags from requirements
    flags_json = await llm.call_json(
        f"Given these requirements, define 3 Unleash feature flags:\n{requirements_doc[:1000]}\n\n"
        f"Return JSON list of 3 flags: [{{name, description, type (release/experiment/ops), enabled: false}}].\n"
        f"Flag 1: a risky major feature\n"
        f"Flag 2: a new user flow ready for A/B test\n"
        f"Flag 3: a gradual rollout feature",
        task_type="requirements",
    )
    if isinstance(flags_json, list):
        flags = flags_json
    else:
        flags = flags_json.get("flags", [
            {"name": "new_dashboard", "description": "New dashboard UI", "type": "release", "enabled": False},
            {"name": "ai_recommendations", "description": "AI-powered recommendations", "type": "experiment", "enabled": False},
            {"name": "bulk_operations", "description": "Bulk data operations", "type": "release", "enabled": False},
        ])

    # Write flags config
    flags_config = output_dir / "unleash_flags_config.json"
    flags_config.write_text(json.dumps({"flags": flags}, indent=2))

    # Write Unleash client integration
    unleash_client_code = """
import os
from UnleashClient import UnleashClient

_client = None

def get_unleash_client() -> UnleashClient:
    global _client
    if _client is None:
        _client = UnleashClient(
            url=os.getenv("UNLEASH_URL", "http://unleash:4242/api"),
            app_name=os.getenv("APP_NAME", "aetheros-app"),
            custom_headers={"Authorization": os.getenv("UNLEASH_TOKEN", "default:development.unleash-insecure-api-token")},
        )
        _client.initialize_client()
    return _client

def is_enabled(flag_name: str, user_id: str = None) -> bool:
    try:
        context = {"userId": user_id} if user_id else {}
        return get_unleash_client().is_enabled(flag_name, context)
    except Exception:
        return False
"""
    unleash_file = project_dir / "src" / "feature_flags.py"
    unleash_file.parent.mkdir(parents=True, exist_ok=True)
    unleash_file.write_text(unleash_client_code)

    # Update .env.example
    env_ex = project_dir / ".env.example"
    if env_ex.exists():
        content = env_ex.read_text()
        if "UNLEASH_URL" not in content:
            env_ex.write_text(content + "\n# Unleash\nUNLEASH_URL=http://localhost:4242/api\nUNLEASH_TOKEN=\n")

    issues = []
    if len(flags) < 3:
        issues.append(f"Only {len(flags)} flags defined (need >= 3)")
    if not unleash_file.exists():
        issues.append("feature_flags.py not written")
    if env_ex.exists() and "UNLEASH_URL" not in env_ex.read_text():
        issues.append("UNLEASH_URL not in .env.example")

    return TaskResult(
        output_path=str(unleash_file),
        confidence=0.9 if not issues else 0.5,
        metadata={"flags": [f["name"] for f in flags], "flag_count": len(flags)},
        issues=issues,
        success=len(flags) >= 3,
    )
