"""Validator registry — discovers and runs all validators in auto_generated/.

Each auto-generated validator module must expose a top-level function::

    def validate(output_dir: str) -> list[str]: ...

that returns a (possibly empty) list of human-readable violation strings.

Usage::

    from aether_os.core.validators.registry import run_auto_generated_validators
    violations = run_auto_generated_validators("/tmp/some_output_dir")
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

_AUTO_GEN_DIR = Path(__file__).parent / "auto_generated"


def _load_module(py_file: Path) -> ModuleType | None:
    """Dynamically load a Python file as a module without registering it in sys.modules."""
    spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
    if spec is None or spec.loader is None:
        logger.warning("[validator_registry] could not create spec for %s", py_file)
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[validator_registry] failed to load %s: %s", py_file, exc)
        return None
    return module


def run_auto_generated_validators(output_dir: str) -> list[str]:
    """Run all validators in the auto_generated/ directory against output_dir.

    Returns a flat list of violation messages from all validators.
    Non-fatal: individual validator failures are logged and skipped.
    """
    violations: list[str] = []

    if not _AUTO_GEN_DIR.exists():
        logger.debug("[validator_registry] auto_generated dir not found — no validators to run")
        return violations

    py_files = sorted(
        f for f in _AUTO_GEN_DIR.iterdir()
        if f.suffix == ".py" and f.name != "__init__.py"
    )

    if not py_files:
        logger.debug("[validator_registry] no auto-generated validators found in %s", _AUTO_GEN_DIR)
        return violations

    for py_file in py_files:
        module = _load_module(py_file)
        if module is None:
            continue
        validate_fn = getattr(module, "validate", None)
        if not callable(validate_fn):
            logger.warning(
                "[validator_registry] %s has no callable validate() — skipping", py_file.name
            )
            continue
        try:
            result = validate_fn(output_dir)
            if isinstance(result, list):
                violations.extend(result)
            else:
                logger.warning(
                    "[validator_registry] %s.validate() returned %s, expected list",
                    py_file.name, type(result).__name__,
                )
        except Exception as exc:
            logger.warning("[validator_registry] %s.validate() raised: %s", py_file.name, exc)

    if violations:
        logger.info(
            "[validator_registry] %d violation(s) found across %d validators",
            len(violations), len(py_files),
        )

    return violations
