"""
p12a_feature_flags — Feature Flag Service with canary/blue-green rollout.

Generates a JSON-file-backed feature flag system supporting:
  - Simple on/off flags (backward compatible)
  - Percentage-based canary rollout (deterministic per user_id via MD5 hash)
  - Blue-green variant assignment
  - Ring-based rollout (internal → beta → production)

NOTE: This is NOT production-grade. For production, use GrowthBook,
LaunchDarkly, or Unleash. The generated system is suitable for local
development, staging, and small-scale deployments only.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p12a_feature_flags.templates import FEATURE_FLAGS_PY
from aether_os.phases.p12a_feature_flags.templates_extras import (
    ADD_FEATURE_FLAGS_SQL,
    FLAG_ADMIN_ROUTER_PY,
    INITIAL_FLAGS_JSON,
    TEST_FEATURE_FLAGS_PY,
)

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p12a_feature_flags: Feature Flag Service with canary rollout.

    Generated files:
      feature_flags/
        __init__.py
        feature_flags.py       — RolloutManager + backward-compat helpers
        flag_admin_router.py   — FastAPI admin endpoints (list/enable/disable/rollout/ring)
        initial_flags.json     — Seed flags in new extended format
        INTEGRATION.md         — Usage instructions
      migrations/
        add_feature_flags.sql  — Schema with rollout_pct, ring, variant columns
      tests/
        test_feature_flags.py  — Deterministic rollout + variant + ring tests
    """
    logger.warning(
        "p12a_feature_flags: generating JSON-file-backed feature flag service. "
        "For production workloads use GrowthBook, LaunchDarkly, or Unleash."
    )

    ff_dir = output_dir / "feature_flags"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"

    ff_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    (ff_dir / "__init__.py").write_text("")

    # Core feature flag module (RolloutManager + module-level helpers)
    (ff_dir / "feature_flags.py").write_text(FEATURE_FLAGS_PY)

    # FastAPI admin router
    (ff_dir / "flag_admin_router.py").write_text(FLAG_ADMIN_ROUTER_PY)

    # Initial flags seed file in new extended format
    (ff_dir / "initial_flags.json").write_text(INITIAL_FLAGS_JSON)

    # Database migration (extended schema)
    (migrations_dir / "add_feature_flags.sql").write_text(ADD_FEATURE_FLAGS_SQL)

    # Integration instructions
    (ff_dir / "INTEGRATION.md").write_text(
        "# Feature Flags Integration\n\n"
        "## Wire the admin router\n\n"
        "```python\n"
        "from feature_flags.flag_admin_router import router as flags_router\n"
        "app.include_router(flags_router)\n"
        "```\n\n"
        "## Simple on/off check\n\n"
        "```python\n"
        "from feature_flags.feature_flags import is_enabled\n"
        "if is_enabled('new_dashboard'):\n"
        "    ...\n"
        "```\n\n"
        "## Canary rollout check\n\n"
        "```python\n"
        "from feature_flags.feature_flags import is_in_rollout\n"
        "if is_in_rollout('new_dashboard', user_id=current_user.id):\n"
        "    ...\n"
        "```\n\n"
        "## Blue/green variant\n\n"
        "```python\n"
        "from feature_flags.feature_flags import get_active_variant\n"
        "variant = get_active_variant('new_dashboard', user_id=current_user.id)\n"
        "# variant == 'blue' or 'green'\n"
        "```\n\n"
        "## Ring-based rollout\n\n"
        "```python\n"
        "from feature_flags.feature_flags import is_in_ring\n"
        "if is_in_ring('new_dashboard', user_ring='beta'):\n"
        "    ...\n"
        "```\n\n"
        "## Admin endpoints\n\n"
        "| Method | Path | Description |\n"
        "|--------|------|-------------|\n"
        "| GET    | /flags/                        | List all flags |\n"
        "| POST   | /flags/{flag}/enable           | Enable (100%) |\n"
        "| POST   | /flags/{flag}/disable          | Disable (0%) |\n"
        "| POST   | /flags/{flag}/rollout          | Set % `{\"percentage\": 25.0}` |\n"
        "| GET    | /flags/{flag}/check?user_id=X  | Check if user in rollout |\n"
        "| POST   | /flags/{flag}/ring             | Set ring `{\"ring\": \"beta\"}` |\n\n"
        "## Environment variable override\n\n"
        "Set `FEATURE_<FLAG_UPPER>=true` to force-enable a flag regardless of JSON config.\n"
        "Set `FEATURE_FLAGS_PATH=/path/to/flags.json` to use a custom file location.\n"
    )

    # Tests
    (test_dir / "test_feature_flags.py").write_text(TEST_FEATURE_FLAGS_PY)

    files_written = [
        "feature_flags/__init__.py",
        "feature_flags/feature_flags.py",
        "feature_flags/flag_admin_router.py",
        "feature_flags/initial_flags.json",
        "feature_flags/INTEGRATION.md",
        "migrations/add_feature_flags.sql",
        "tests/test_feature_flags.py",
    ]

    logger.info("p12a_feature_flags: wrote %d files to %s", len(files_written), output_dir)

    return TaskResult(
        output_path=str(ff_dir),
        confidence=0.92,
        metadata={
            "files_written": len(files_written),
            "rollout_features": [
                "percentage_rollout",
                "blue_green_variant",
                "ring_based_rollout",
                "deterministic_hash",
                "thread_safe_rlock",
                "backward_compatible_api",
            ],
        },
        issues=[],
        success=True,
    )
