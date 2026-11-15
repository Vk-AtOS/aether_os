"""
Aether-One Framework & Plugin Generators

Purpose
-------
Generate real, on-disk code scaffolds for common frameworks:

- Django (FinTech / ERP style backends)
- Next.js (Healthcare / general frontends)
- ROS2-style Python nodes (for robotics / IoT control)
- Firmware C skeletons for edge devices

This module is *enterprise-facing*:

- Deterministic, pure Python (no network).
- Writes files under `generated/<app_name>/...` inside the project root.
- Integrates with `prompt_templates` to also return a PromptBundle
  that higher-level agents / LLMs can use to further flesh out the project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List

from .prompts import (
    build_prompt_bundle,
    PromptBundle,
)
from .generators_helpers import (
    _django_files,
    _nextjs_files,
    _ros2_py_files,
    _firmware_c_files,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GeneratedFile:
    """
    One file that will be created on disk.

    path:
        Absolute path where the file will be written.

    relpath:
        Path relative to the project root (for display / logging).

    content:
        Full file content.
    """

    path: str
    relpath: str
    content: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationRequest:
    """
    Request parameters for a framework generation.

    Fields:
        project_path:
            Root project directory (Aether-One repo, or client repo).

        app_name:
            Name of the generated app / service (used in folder names).

        domain:
            Business domain: 'fintech', 'healthcare', 'iot', 'gaming', 'erp', ...

        task:
            Template task: typically 'app_scaffold' or 'firmware_stub'.

        target:
            Framework target: 'django', 'nextjs', 'ros2_py', 'firmware_c'.

        requirements:
            Free-form client requirements to feed into prompt templates.

        context:
            Extra structured context (modules list, device_type, etc.).
    """

    project_path: str
    app_name: str
    domain: str
    task: str
    target: str
    requirements: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationPlan:
    """
    Plan describing the scaffold and prompt bundle.

    Fields:
        root_path:
            Absolute root folder where files will be generated,
            typically `<project_path>/generated/<app_name>`.

        files:
            List of GeneratedFile instances.

        prompt_bundle:
            PromptBundle used to guide (optional) LLM elaboration.

        metadata:
            Arbitrary extra metadata.
    """

    root_path: str
    files: List[GeneratedFile]
    prompt_bundle: PromptBundle
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["files"] = [f.to_dict() for f in self.files]
        d["prompt_bundle"] = self.prompt_bundle.to_dict()
        return d


@dataclass
class ApplyResult:
    """
    Result of applying a GenerationPlan.

    Fields:
        root_path:
            Path where the scaffold was written.

        written_files:
            List of file relative paths that were created/overwritten.

        skipped_files:
            Files that were skipped (e.g. overwrite=False and file exists).
    """

    root_path: str
    written_files: List[str]
    skipped_files: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_project_path(project_path: str) -> str:
    return os.path.abspath(os.path.expanduser(project_path))


def _join_safe(root: str, *parts: str) -> str:
    """
    Join paths and prevent escaping the root directory.
    """
    path = os.path.abspath(os.path.join(root, *parts))
    root_abs = os.path.abspath(root)
    if not path.startswith(root_abs):
        raise ValueError(f"Unsafe path outside root: {path!r}")
    return path


# Framework generators (_django_files, _nextjs_files, _ros2_py_files,
# _firmware_c_files) live in generators_helpers.py — imported above.


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_generation_plan(req: GenerationRequest) -> GenerationPlan:
    """
    Build a GenerationPlan for the given framework request.

    This will:
        - Normalise project path
        - Determine a safe root directory: <project>/generated/<app_name>
        - Generate a set of file contents for the target framework
        - Build a PromptBundle from prompt_templates for the corresponding
          (domain, task, target) so LLMs can further expand the scaffold.
    """
    project_abs = _normalize_project_path(req.project_path)
    app_name = req.app_name.strip() or "app"
    target = req.target.lower()

    root = _join_safe(project_abs, "generated", app_name)

    # Select framework-specific files
    if target == "django":
        file_map = _django_files(app_name)
    elif target == "nextjs":
        file_map = _nextjs_files(app_name)
    elif target == "ros2_py":
        file_map = _ros2_py_files(app_name)
    elif target == "firmware_c":
        file_map = _firmware_c_files(app_name)
    else:
        raise ValueError(f"Unsupported target framework: {target!r}")

    files: List[GeneratedFile] = []
    for relpath, content in file_map.items():
        abs_path = _join_safe(root, relpath)
        rel_from_project = os.path.relpath(abs_path, project_abs)
        files.append(
            GeneratedFile(
                path=abs_path,
                relpath=rel_from_project,
                content=content,
            )
        )

    # Prompt bundle for this domain+task+target
    prompt_bundle: PromptBundle = build_prompt_bundle(
        domain=req.domain,
        task=req.task,
        target=req.target,
        requirements=req.requirements,
        context=req.context,
    )

    meta = {
        "project_path": project_abs,
        "app_name": app_name,
        "target": target,
    }

    return GenerationPlan(
        root_path=root,
        files=files,
        prompt_bundle=prompt_bundle,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Plan application
# ---------------------------------------------------------------------------


def apply_generation_plan(
    plan: GenerationPlan,
    *,
    overwrite: bool = False,
) -> ApplyResult:
    """
    Apply a previously built GenerationPlan to the filesystem.

    - Creates directories as needed.
    - Writes each file, optionally skipping existing ones if overwrite=False.
    """
    written: List[str] = []
    skipped: List[str] = []

    for gf in plan.files:
        os.makedirs(os.path.dirname(gf.path), exist_ok=True)
        if not overwrite and os.path.exists(gf.path):
            skipped.append(gf.relpath)
            continue
        with open(gf.path, "w", encoding="utf-8") as f:
            f.write(gf.content)
        written.append(gf.relpath)

    return ApplyResult(
        root_path=plan.root_path,
        written_files=written,
        skipped_files=skipped,
    )
