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
from typing import Any, Dict, List, Optional

from .prompts import (
    build_prompt_bundle,
    PromptBundle,
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


# ---------------------------------------------------------------------------
# Template-based file content generators
# ---------------------------------------------------------------------------


def _django_files(app_name: str) -> Dict[str, str]:
    """
    Minimal but real Django-style app layout.

    NOTE: This does not create a fully runnable project with manage.py;
    it creates a *service app* skeleton that can be plugged into a larger
    Django project.
    """
    app_pkg = app_name.lower().replace("-", "_")

    files: Dict[str, str] = {}

    files[f"{app_pkg}/__init__.py"] = ""

    files[f"{app_pkg}/models.py"] = f'''"""
Django models for the {app_name} service.

This module is intentionally minimal and ready to be extended by
generated or human-written code.
"""

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base class with created/updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Customer(TimeStampedModel):
    external_id = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return f"Customer({{self.external_id}})"


class LedgerEntry(TimeStampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=8, default="INR")
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
'''

    files[f"{app_pkg}/serializers.py"] = f'''"""
DRF serializers for the {app_name} service.
"""

from rest_framework import serializers
from . import models


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Customer
        fields = ["id", "external_id", "full_name", "created_at", "updated_at"]


class LedgerEntrySerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)

    class Meta:
        model = models.LedgerEntry
        fields = [
            "id",
            "customer",
            "amount",
            "currency",
            "description",
            "created_at",
            "updated_at",
        ]
'''

    files[f"{app_pkg}/views.py"] = f'''"""
API views for the {app_name} service.
"""

from rest_framework import viewsets
from . import models, serializers


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = models.Customer.objects.all()
    serializer_class = serializers.CustomerSerializer


class LedgerEntryViewSet(viewsets.ModelViewSet):
    queryset = models.LedgerEntry.objects.select_related("customer")
    serializer_class = serializers.LedgerEntrySerializer
'''

    files[f"{app_pkg}/urls.py"] = f'''"""
URL routing for the {app_name} service.

Include this router from your project-level urls.py:

    path("api/{app_pkg}/", include("{app_pkg}.urls"))
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register(r"customers", views.CustomerViewSet, basename="customer")
router.register(r"ledger", views.LedgerEntryViewSet, basename="ledger")

urlpatterns = [
    path("", include(router.urls)),
]
'''

    return files


def _nextjs_files(app_name: str) -> Dict[str, str]:
    """
    Minimal Next.js / React layout for a healthcare-style portal.
    """

    safe_name = app_name.replace(" ", "-").lower()
    files: Dict[str, str] = {}

    files["package.json"] = f'''{{
  "name": "{safe_name}",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }},
  "dependencies": {{
    "next": "14.0.0",
    "react": "18.0.0",
    "react-dom": "18.0.0"
  }}
}}
'''

    files["next.config.js"] = """/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
"""

    files["pages/_app.tsx"] = """import type { AppProps } from "next/app";

export default function App({ Component, pageProps }: AppProps) {
  return <Component {...pageProps} />;
}
"""

    files["pages/index.tsx"] = """import Link from "next/link";

export default function Home() {
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>Healthcare Portal</h1>
      <p>Select a role to continue:</p>
      <ul>
        <li><Link href="/patient">Patient</Link></li>
        <li><Link href="/clinician">Clinician</Link></li>
        <li><Link href="/admin">Admin</Link></li>
      </ul>
    </main>
  );
}
"""

    files["pages/patient.tsx"] = """export default function PatientDashboard() {
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>Patient Dashboard</h1>
      <p>Placeholder view for patient records.</p>
    </main>
  );
}
"""

    files["pages/clinician.tsx"] = """export default function ClinicianDashboard() {
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>Clinician Dashboard</h1>
      <p>Placeholder view for clinician tools.</p>
    </main>
  );
}
"""

    files["pages/admin.tsx"] = """export default function AdminDashboard() {
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>Admin Dashboard</h1>
      <p>Placeholder view for system administration.</p>
    </main>
  );
}
"""

    return files


def _ros2_py_files(app_name: str) -> Dict[str, str]:
    """
    Skeleton ROS2-style Python node for robotics / IoT control.
    """
    safe_name = app_name.replace("-", "_").lower()
    pkg_dir = safe_name
    files: Dict[str, str] = {}

    files[f"{pkg_dir}/__init__.py"] = ""

    files[f"{pkg_dir}/node.py"] = f'''"""
ROS2-style node skeleton for {app_name}.

This code does not assume any particular message types; it is intended
to be adapted into a real robotics / IoT node.
"""

import rclpy
from rclpy.node import Node


class {safe_name.capitalize()}Node(Node):
    def __init__(self) -> None:
        super().__init__("{safe_name}_node")
        self.get_logger().info("Node initialised.")
        # TODO: declare parameters, publishers, and subscriptions here.

    def tick(self) -> None:
        # TODO: main control loop tick.
        self.get_logger().debug("Tick.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = {safe_name.capitalize()}Node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
'''

    files["setup.py"] = f'''from setuptools import setup

package_name = "{safe_name}"

setup(
    name=package_name,
    version="0.0.1",
    packages=[package_name],
    data_files=[],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="aether-one",
    maintainer_email="dev@example.com",
    description="Skeleton ROS2 node generated by Aether-One.",
    license="MIT",
    tests_require=["pytest"],
)
'''

    return files


def _firmware_c_files(app_name: str) -> Dict[str, str]:
    """
    Bare-metal-ish C firmware skeleton.
    """
    safe_name = app_name.replace(" ", "_").lower()
    files: Dict[str, str] = {}

    files["main.c"] = f"""#include "platform.h"
#include "control.h"

/*
 * Firmware skeleton generated by Aether-One for: {app_name}
 *
 * This code is intentionally conservative and portable.
 * All chip-specific details should be implemented inside platform.c/h.
 */

int main(void) {{
    platform_init();

    while (1) {{
        platform_poll();
        control_tick();
    }}

    // Typically unreachable
    return 0;
}}
"""

    files["platform.h"] = """#pragma once

/*
 * Platform abstraction for clocks, GPIO, and peripherals.
 * Implement these functions for your specific MCU and board.
 */

void platform_init(void);
void platform_poll(void);
"""

    files["platform.c"] = """#include "platform.h"

/*
 * Chip-specific initialisation goes here.
 */
void platform_init(void) {
    // TODO: initialise clocks, GPIO, peripherals, etc.
}

/*
 * Optional polling hook for peripherals or background tasks.
 */
void platform_poll(void) {
    // TODO: service peripherals, handle background work, etc.
}
"""

    files["control.h"] = """#pragma once

/*
 * Application-level control layer.
 * For example: read sensors, update state, drive actuators.
 */

void control_tick(void);
"""

    files["control.c"] = """#include "control.h"

/*
 * Main control loop tick called from main().
 * Implement your application logic here.
 */
void control_tick(void) {
    // TODO: read sensors, apply control law, update actuators.
}
"""

    files["README.md"] = f"""# Firmware Skeleton: {app_name}

Generated by Aether-One.

This skeleton is intentionally generic. Implement all hardware-specific
details inside `platform.c/h` and your application logic in `control.c`.
"""

    return files


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
