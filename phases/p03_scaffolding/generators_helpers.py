"""
Framework file template generators for Aether-One scaffolding.

These pure functions return a dict of {relative_path: content} for each
supported framework target. They are called by build_generation_plan() in
generators.py.
"""

from __future__ import annotations

from typing import Dict


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
