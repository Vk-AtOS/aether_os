"""Validator package — static and auto-generated validators for AetherOS generated apps.

Public API::

    from aether_os.core.validators import run_all_validators
    violations = run_all_validators("/path/to/generated/app/output")

run_all_validators() returns a list of human-readable violation strings.
An empty list means all validators passed.
"""
from __future__ import annotations

from aether_os.core.validators.registry import run_auto_generated_validators


def run_all_validators(output_dir: str) -> list[str]:
    """Run all registered validators (auto-generated + any future built-ins) against output_dir.

    Returns a flat list of violation strings. Empty list means all checks passed.
    Individual validator failures are non-fatal and logged as warnings.
    """
    violations: list[str] = []
    violations.extend(run_auto_generated_validators(output_dir))
    return violations


__all__ = ["run_all_validators"]
