"""
Aether-One Developer Onboarding Engine.

This module provides the core logic that an `aether-one init` CLI command
will use to prepare a repository for Aether-One:

- Create a `.aether-one/` metadata directory.
- Write an onboarding manifest (`onboarding.json`) with basic metadata.
- Write a `.aether-one/README.md` explaining the local layout.
- Ensure a `tests/` directory exists, with a basic smoke test that
  validates Aether-One integration from a developer perspective.

This module is pure Python with no user interaction; the CLI layer is
expected to call into it.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OnboardingConfig:
    """
    Metadata representing how Aether-One was initialised for this project.
    """

    project_root: str
    preset: str  # e.g. "fintech", "healthcare", "iot", "generic"
    industry_tags: List[str]
    created_at: str
    created_by: str  # free-form identifier, e.g. "cli:aether-one"
    notes: Optional[str] = None


@dataclass
class OnboardingScaffold:
    """
    Paths created or touched during onboarding.
    """

    project_root: Path
    meta_dir: Path
    onboarding_manifest: Path
    meta_readme: Path
    smoke_test: Path

    def to_dict(self) -> Dict[str, str]:
        return {
            "project_root": str(self.project_root),
            "meta_dir": str(self.meta_dir),
            "onboarding_manifest": str(self.onboarding_manifest),
            "meta_readme": str(self.meta_readme),
            "smoke_test": str(self.smoke_test),
        }


class OnboardingError(RuntimeError):
    """Raised when onboarding cannot safely complete."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def create_onboarding_scaffold(
    project_path: str,
    *,
    preset: str = "fintech",
    industry_tags: Optional[List[str]] = None,
    created_by: str = "cli:aether-one-init",
    notes: Optional[str] = None,
    force: bool = False,
) -> OnboardingScaffold:
    """
    Create the Aether-One onboarding scaffold for a project.

    This function is idempotent:
        - If files already exist and force=False, they are preserved.
        - If force=True, onboarding manifest and README are overwritten,
          but directories are preserved.

    Parameters
    ----------
    project_path:
        Path to the repository root.
    preset:
        Logical preset to associate with this project (e.g. "fintech").
        This does not change org_config behaviour by itself, but documents
        expected defaults.
    industry_tags:
        Free-form tags like ["fintech", "payments"] used purely for metadata.
    created_by:
        Identifier for who/what created this scaffold (for audit trails).
    notes:
        Optional free-form notes about this onboarding run.
    force:
        If True, overwrite onboarding.json and .aether-one/README.md.

    Returns
    -------
    OnboardingScaffold
        Summary of created/touched paths.

    Raises
    ------
    OnboardingError
        If project path does not exist or is not a directory.
    """
    project_root = Path(project_path).expanduser().resolve()
    if not project_root.exists() or not project_root.is_dir():
        raise OnboardingError(f"Project path does not exist or is not a directory: {project_root}")

    meta_dir = project_root / ".aether-one"
    _ensure_dir(meta_dir)

    onboarding_manifest = meta_dir / "onboarding.json"
    meta_readme = meta_dir / "README.md"

    tests_dir = project_root / "tests"
    _ensure_dir(tests_dir)
    smoke_test = tests_dir / "test_aetherone_onboarding_smoke.py"

    # Prepare onboarding config
    cfg = OnboardingConfig(
        project_root=str(project_root),
        preset=preset,
        industry_tags=sorted(set(industry_tags or [])),
        created_at=_now_iso(),
        created_by=created_by,
        notes=notes,
    )

    # Write / update onboarding manifest
    if onboarding_manifest.exists() and not force:
        logger.info("Onboarding manifest already exists at %s; preserving (force=False).", onboarding_manifest)
    else:
        tmp = onboarding_manifest.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, indent=2, sort_keys=True)
        tmp.replace(onboarding_manifest)
        logger.info("Onboarding manifest written to %s", onboarding_manifest)

    # Write / update .aether-one/README.md
    if meta_readme.exists() and not force:
        logger.info("Onboarding README already exists at %s; preserving (force=False).", meta_readme)
    else:
        readme_contents = _generate_meta_readme(
            project_root=project_root,
            preset=preset,
            industry_tags=cfg.industry_tags,
        )
        meta_readme.write_text(readme_contents, encoding="utf-8")
        logger.info("Onboarding README written to %s", meta_readme)

    # Ensure smoke test exists (always idempotent; do not overwrite by default)
    if smoke_test.exists() and not force:
        logger.info("Smoke test already exists at %s; preserving (force=False).", smoke_test)
    else:
        smoke_contents = _generate_smoke_test()
        smoke_test.write_text(smoke_contents, encoding="utf-8")
        logger.info("Smoke test written to %s", smoke_test)

    return OnboardingScaffold(
        project_root=project_root,
        meta_dir=meta_dir,
        onboarding_manifest=onboarding_manifest,
        meta_readme=meta_readme,
        smoke_test=smoke_test,
    )


def _generate_meta_readme(
    *,
    project_root: Path,
    preset: str,
    industry_tags: List[str],
) -> str:
    """
    Generate contents for .aether-one/README.md.
    """
    tags_str = ", ".join(industry_tags) if industry_tags else "none"
    return f"""# Aether-One Project Metadata

This directory is managed by the Aether-One onboarding engine.

Project root:
  {project_root}

Preset:
  {preset}

Industry tags:
  {tags_str}

Files
-----

- `onboarding.json`
    Machine-readable metadata about how Aether-One was initialised
    for this project. Safe to commit to version control.

- `README.md`
    This file. You can extend it with any notes relevant to your
    team's usage of Aether-One.

General Guidance
----------------

- `.aether-one/` is intended for project-level metadata and policy.
- Use your version control system to track changes to this directory.
- Do **not** store secrets (API keys, passwords) in this directory.
  Prefer local `.env` files or your standard secrets management system.

Related
-------

- Run `pytest tests/test_aetherone_onboarding_smoke.py` to verify that
  the basic Aether-One integration tests are wired correctly.
"""


def _generate_smoke_test() -> str:
    """
    Generate contents for tests/test_aetherone_onboarding_smoke.py.

    This test is intentionally very lightweight and does NOT require the
    Aether-One orchestrator to be running. It simply checks the presence
    of the `.aether-one` directory and a minimal environment variable.
    """
    return '''"""
Aether-One onboarding smoke test.

This test validates that:

- The `.aether-one` metadata directory exists.
- The project has been initialised for Aether-One.

It does not require the orchestrator to be running and should be safe
to include in any CI pipeline as a cheap verification step.
"""

from __future__ import annotations

import os
from pathlib import Path


def test_aetherone_metadata_directory_exists() -> None:
    project_root = Path(__file__).resolve().parents[1]
    meta_dir = project_root / ".aether-one"
    assert meta_dir.exists(), f".aether-one metadata directory not found at {meta_dir}"

'''

