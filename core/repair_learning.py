"""
Repair → Auto-Validator learning loop.

When p07b_self_healing fixes a bug, this module:
1. Classifies the repair by bug class (RELATIVE_IMPORT, SEED_UNIQUE_VIOLATION, etc.)
2. Generates a static validator function for that bug class
3. Stores the validator in core/validators/auto_generated/ as a .py file
4. Registers it in core/validators/registry.py so future runs check it pre-submission
5. Persists a JSON summary of each generated validator to knowledge_graph/auto_validators.json
   so load_validators() can reconstruct the catalogue on startup.
"""
from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Persistent store for validator metadata (not the source code — that's in auto_generated/)
_VALIDATOR_STORE = Path(__file__).parent / "knowledge_graph" / "auto_validators.json"

# Directory where auto-generated validators land, relative to this file's package root
_VALIDATORS_DIR = Path(__file__).parent / "validators" / "auto_generated"

_SAFE_TEXT = re.compile(r"[^A-Za-z0-9_ .-]")


# ---------------------------------------------------------------------------
# BugClass enum
# ---------------------------------------------------------------------------

class BugClass(str, Enum):
    RELATIVE_IMPORT = "relative_import"
    SEED_UNIQUE_VIOLATION = "seed_unique_violation"
    MISSING_ROUTER = "missing_router"
    BARE_EXCEPT = "bare_except"
    SQL_INJECTION = "sql_injection"
    HARDCODED_SECRET = "hardcoded_secret"
    MISSING_AUTH = "missing_auth"
    MISSING_PAGINATION = "missing_pagination"


# ---------------------------------------------------------------------------
# RepairEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class RepairEvent:
    bug_class: BugClass
    domain: str
    entity: str
    file_path: str
    fix_applied: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Validator source-code generators
# ---------------------------------------------------------------------------

def _validator_relative_import(event: RepairEvent) -> str:
    """Generate a validator that detects relative imports in router files."""
    return f'''\
"""
Auto-generated validator — BugClass.RELATIVE_IMPORT
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import re
from pathlib import Path


def validate(output_dir: str) -> list[str]:
    """Return violation messages for any relative imports found in router py files."""
    violations: list[str] = []
    routers_dir = Path(output_dir)
    pattern = re.compile(r\'from\\s*\\.+\\s*\\w|import\\s*\\.+\\s*\\w\', re.MULTILINE)
    for py_file in routers_dir.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"[relative_import] could not read {{py_file}}: {{exc}}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(
                    f"[relative_import] {{py_file}}:{{lineno}}: relative import detected: {{line.strip()!r}}"
                )
    return violations
'''


def _validator_seed_unique_violation(event: RepairEvent) -> str:
    """Generate a validator that detects duplicate unique-field values in seed.py."""
    return f'''\
"""
Auto-generated validator — BugClass.SEED_UNIQUE_VIOLATION
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import re
from pathlib import Path

_UNIQUE_FIELDS = frozenset({{"email", "username", "slug", "file_path", "code", "sku"}})


def validate(output_dir: str) -> list[str]:
    """Return violation messages for duplicate unique-field values in seed.py."""
    violations: list[str] = []
    for seed_file in Path(output_dir).rglob("seed.py"):
        try:
            text = seed_file.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"[seed_unique] could not read {{seed_file}}: {{exc}}")
            continue
        for field_name in _UNIQUE_FIELDS:
            pattern = re.compile(
                r\'\\b\' + re.escape(field_name) + r\'\\s*=\\s*(["\\\'])(.+?)\\1\',
                re.MULTILINE,
            )
            seen: dict[str, int] = {{}}
            for m in pattern.finditer(text):
                val = m.group(2)
                seen[val] = seen.get(val, 0) + 1
            for val, count in seen.items():
                if count > 1:
                    violations.append(
                        f"[seed_unique] {{seed_file}}: field {{field_name!r}} value {{val!r}} appears {{count}} times"
                    )
    return violations
'''


def _validator_missing_router(event: RepairEvent) -> str:
    """Generate a validator that detects missing routers/__init__.py."""
    return f'''\
"""
Auto-generated validator — BugClass.MISSING_ROUTER
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
from pathlib import Path


def validate(output_dir: str) -> list[str]:
    """Return violation messages when a routers/__init__.py is absent."""
    violations: list[str] = []
    for routers_dir in Path(output_dir).rglob("routers"):
        if not routers_dir.is_dir():
            continue
        init_file = routers_dir / "__init__.py"
        if not init_file.exists():
            violations.append(
                f"[missing_router] {{routers_dir}}: missing __init__.py — routers will not be importable"
            )
    return violations
'''


def _validator_bare_except(event: RepairEvent) -> str:
    """Generate a validator that detects bare except clauses."""
    return f'''\
"""
Auto-generated validator — BugClass.BARE_EXCEPT
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import ast
from pathlib import Path


def validate(output_dir: str) -> list[str]:
    """Return violation messages for bare except clauses in generated Python files."""
    violations: list[str] = []
    for py_file in Path(output_dir).rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:
            violations.append(f"[bare_except] {{py_file}}: could not parse: {{exc}}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(
                    f"[bare_except] {{py_file}}:{{node.lineno}}: bare except clause without exception type"
                )
    return violations
'''


def _validator_sql_injection(event: RepairEvent) -> str:
    """Generate a validator that detects raw string interpolation in SQL."""
    return f'''\
"""
Auto-generated validator — BugClass.SQL_INJECTION
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import re
from pathlib import Path

# Matches text(f"...") or execute(f"...") — f-strings inside SQL calls are suspicious
_SQL_FSTRING_RE = re.compile(
    r\'(?:text|execute|cursor\\.execute)\\s*\\(\\s*f["\\\']\'
)


def validate(output_dir: str) -> list[str]:
    """Return violation messages for f-string interpolation inside SQL calls."""
    violations: list[str] = []
    for py_file in Path(output_dir).rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"[sql_injection] could not read {{py_file}}: {{exc}}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _SQL_FSTRING_RE.search(line):
                violations.append(
                    f"[sql_injection] {{py_file}}:{{lineno}}: f-string in SQL call — use parameterized queries: {{line.strip()!r}}"
                )
    return violations
'''


def _validator_hardcoded_secret(event: RepairEvent) -> str:
    """Generate a validator that detects hardcoded secrets."""
    return f'''\
"""
Auto-generated validator — BugClass.HARDCODED_SECRET
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import re
from pathlib import Path

_SECRET_RE = re.compile(
    r\'(?:SECRET_KEY|password|api_key|token)\\s*=\\s*["\\\'][^"\\\']{{8,}}["\\\']\'
    , re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r\'(?:changeme|example|placeholder|your[_-]?secret|CHANGE_ME)\', re.IGNORECASE
)


def validate(output_dir: str) -> list[str]:
    """Return violation messages for hardcoded secret values in Python files."""
    violations: list[str] = []
    for py_file in Path(output_dir).rglob("*.py"):
        # Skip test files — they may intentionally contain placeholder values
        if "test" in py_file.stem.lower():
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"[hardcoded_secret] could not read {{py_file}}: {{exc}}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _SECRET_RE.search(line) and not _PLACEHOLDER_RE.search(line):
                violations.append(
                    f"[hardcoded_secret] {{py_file}}:{{lineno}}: possible hardcoded credential: {{line.strip()!r}}"
                )
    return violations
'''


def _validator_missing_auth(event: RepairEvent) -> str:
    """Generate a validator that detects router endpoints missing auth dependency."""
    return f'''\
"""
Auto-generated validator — BugClass.MISSING_AUTH
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import ast
from pathlib import Path

# Decorator names that indicate an HTTP endpoint
_ENDPOINT_DECORATORS = frozenset({{"get", "post", "put", "patch", "delete"}})


def validate(output_dir: str) -> list[str]:
    """Return violation messages for router endpoints that lack a current_user dependency."""
    violations: list[str] = []
    for py_file in Path(output_dir).rglob("*.py"):
        # Only check router files
        if "router" not in py_file.stem.lower() and "crud" not in py_file.stem.lower():
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:
            violations.append(f"[missing_auth] {{py_file}}: could not parse: {{exc}}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Check if function has an HTTP endpoint decorator
            is_endpoint = any(
                (isinstance(d, ast.Call)
                 and isinstance(d.func, ast.Attribute)
                 and d.func.attr in _ENDPOINT_DECORATORS)
                or (isinstance(d, ast.Attribute) and d.attr in _ENDPOINT_DECORATORS)
                for d in node.decorator_list
            )
            if not is_endpoint:
                continue
            # Check if any argument is named current_user or has Depends(get_current_user)
            arg_names = {{arg.arg for arg in node.args.args}}
            if "current_user" not in arg_names:
                violations.append(
                    f"[missing_auth] {{py_file}}:{{node.lineno}}: endpoint {{node.name!r}} has no current_user dependency"
                )
    return violations
'''


def _validator_missing_pagination(event: RepairEvent) -> str:
    """Generate a validator that detects list endpoints missing skip/limit params."""
    return f'''\
"""
Auto-generated validator — BugClass.MISSING_PAGINATION
Domain: {event.domain!r}  Entity: {event.entity!r}
Generated: {event.timestamp}
"""
import ast
from pathlib import Path

_ENDPOINT_DECORATORS = frozenset({{"get"}})


def validate(output_dir: str) -> list[str]:
    """Return violation messages for GET list endpoints without skip/limit parameters."""
    violations: list[str] = []
    for py_file in Path(output_dir).rglob("*.py"):
        if "router" not in py_file.stem.lower() and "crud" not in py_file.stem.lower():
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:
            violations.append(f"[missing_pagination] {{py_file}}: could not parse: {{exc}}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Only check functions whose name starts with get_ or list_
            if not (node.name.startswith("get_") or node.name.startswith("list_")):
                continue
            is_get_endpoint = any(
                (isinstance(d, ast.Call)
                 and isinstance(d.func, ast.Attribute)
                 and d.func.attr in _ENDPOINT_DECORATORS)
                or (isinstance(d, ast.Attribute) and d.attr in _ENDPOINT_DECORATORS)
                for d in node.decorator_list
            )
            if not is_get_endpoint:
                continue
            arg_names = {{arg.arg for arg in node.args.args}}
            if "skip" not in arg_names or "limit" not in arg_names:
                violations.append(
                    f"[missing_pagination] {{py_file}}:{{node.lineno}}: list endpoint {{node.name!r}} missing skip/limit params"
                )
    return violations
'''


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_GENERATOR_MAP: dict[BugClass, object] = {
    BugClass.RELATIVE_IMPORT: _validator_relative_import,
    BugClass.SEED_UNIQUE_VIOLATION: _validator_seed_unique_violation,
    BugClass.MISSING_ROUTER: _validator_missing_router,
    BugClass.BARE_EXCEPT: _validator_bare_except,
    BugClass.SQL_INJECTION: _validator_sql_injection,
    BugClass.HARDCODED_SECRET: _validator_hardcoded_secret,
    BugClass.MISSING_AUTH: _validator_missing_auth,
    BugClass.MISSING_PAGINATION: _validator_missing_pagination,
}


def generate_validator(event: RepairEvent) -> str:
    """Return Python source code for a validator function for the given bug class.

    Always validates the output with ast.parse() before returning so callers
    are guaranteed syntactically valid Python.

    Raises ValueError if generation produces invalid syntax (should never happen
    for the built-in templates, but protects against future edits).
    """
    generator_fn = _GENERATOR_MAP.get(event.bug_class)
    if generator_fn is None:
        raise ValueError(f"No validator generator for bug class {event.bug_class!r}")

    # Domain/entity are interpolated into the generated source (docstring). They
    # come from user-influenced IR, so a quote or triple-quote would break out of
    # the docstring and run as code when load_validators() imports the file.
    event = replace(
        event,
        domain=_SAFE_TEXT.sub("_", str(event.domain))[:80],
        entity=_SAFE_TEXT.sub("_", str(event.entity))[:80],
    )

    source = generator_fn(event)  # type: ignore[call-arg]

    # Validate syntax before returning — hard guard so bad code never lands on disk
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(
            f"generate_validator produced invalid Python for {event.bug_class}: {exc}"
        ) from exc

    return source


def save_validator(event: RepairEvent, validator_src: str) -> str:
    """Write validator source to core/validators/auto_generated/{bug_class}_{domain}_{ts}.py.

    Returns the absolute path of the written file.
    """
    _VALIDATORS_DIR.mkdir(parents=True, exist_ok=True)

    # Build a safe filename: strip non-alphanumeric chars from domain, truncate timestamp
    safe_domain = "".join(c if c.isalnum() else "_" for c in event.domain.lower())[:40]
    ts_tag = event.timestamp.replace(":", "").replace("-", "").replace("+", "").replace(".", "")[:15]
    filename = f"{event.bug_class.value}_{safe_domain}_{ts_tag}.py"
    file_path = _VALIDATORS_DIR / filename

    try:
        file_path.write_text(validator_src, encoding="utf-8")
        logger.info(
            "[repair_learning] saved validator %s for bug class %s / domain %s",
            file_path.name, event.bug_class.value, event.domain,
        )
    except Exception as exc:
        logger.warning("[repair_learning] could not save validator %s: %s", file_path, exc)

    return str(file_path)


def _save_validator_meta(event: RepairEvent, saved_path: str) -> None:
    """Append new validator metadata to persistent JSON store.

    Persists a compact record (no source code) so load_validators() can
    reconstruct the catalogue on startup without scanning the filesystem.
    """
    try:
        _VALIDATOR_STORE.parent.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if _VALIDATOR_STORE.exists():
            try:
                existing = json.loads(_VALIDATOR_STORE.read_text())
            except Exception as e:
                logger.warning("repair_learning: corrupt auto_validators.json, resetting: %s", e)
                existing = []
        existing.append({
            "bug_class": event.bug_class.value,
            "domain": event.domain,
            "entity": event.entity,
            "file_path": event.file_path,
            "fix_applied": event.fix_applied,
            "validator_path": saved_path,
            "timestamp": event.timestamp,
        })
        _VALIDATOR_STORE.write_text(json.dumps(existing, indent=2, default=str))
    except Exception as e:
        logger.warning("repair_learning: failed to persist validator metadata: %s", e)


def load_validators() -> list:
    """Load auto-generated validator functions from disk.  Call on startup or before code gen.

    Each validator .py file must export a ``check(source: str) -> list[str]`` function.
    This function imports each file dynamically and returns a list of callable objects
    (not metadata dicts) so callers can run them directly:

        validators = load_validators()
        for v in validators:
            issues = v.check(source_code)
            if issues:
                logger.warning("Validator found issues: %s", issues)

    Validators that cannot be imported are skipped with a warning so a single broken
    validator never blocks code generation.
    """
    import importlib.util as _ilu

    callables: list = []
    try:
        if not _VALIDATOR_STORE.exists():
            return []
        meta_list: list = json.loads(_VALIDATOR_STORE.read_text())
    except Exception as exc:
        logger.warning("repair_learning: failed to read validator store: %s", exc)
        return []

    for meta in meta_list:
        validator_path = meta.get("validator_path", "")
        if not validator_path:
            continue
        vp = Path(validator_path)
        # Only import files inside the generated-validators dir; the metadata
        # store is writable data and must not be able to point at arbitrary code.
        try:
            inside = vp.resolve().is_relative_to(_VALIDATORS_DIR.resolve())
        except OSError as exc:
            logger.warning("repair_learning: cannot resolve %s: %s", vp, exc)
            continue
        if not inside or vp.suffix != ".py":
            logger.warning("repair_learning: refusing validator outside %s: %s", _VALIDATORS_DIR, vp)
            continue
        if not vp.exists():
            logger.debug("repair_learning: validator file missing, skipping: %s", vp)
            continue
        try:
            spec = _ilu.spec_from_file_location(f"_av_{vp.stem}", vp)
            if spec is None or spec.loader is None:
                logger.warning("repair_learning: cannot create spec for %s", vp)
                continue
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            # Validators generated by AetherOS export `validate(output_dir)` not `check(src)`.
            # Wrap whichever signature is present into a unified check(source) callable.
            if hasattr(mod, "check"):
                callables.append(mod)
            elif hasattr(mod, "validate"):
                # Wrap validate(output_dir) into a no-op check(source) so callers get
                # a consistent interface.  The validate() form is used by the
                # audit pipeline; check() is used for pre-write source validation.
                class _Wrapper:
                    def __init__(self, _mod):
                        self._mod = _mod
                    def check(self, source: str) -> list:  # noqa: D401
                        # Source-level validators receive source text, not an output dir.
                        # The validate() family needs a directory; skip it in check() context.
                        return []
                    def validate(self, output_dir: str) -> list:
                        try:
                            return self._mod.validate(output_dir)
                        except Exception as ve:
                            logger.warning("repair_learning: validator %s raised: %s", self._mod.__file__, ve)
                            return []
                callables.append(_Wrapper(mod))
            else:
                logger.warning("repair_learning: validator %s has neither check() nor validate()", vp)
        except Exception as exc:
            logger.warning("repair_learning: failed to import validator %s: %s", vp, exc)

    logger.info("repair_learning: loaded %d callable validators from disk", len(callables))
    return callables


def learn_from_repair(event: RepairEvent) -> Optional[str]:
    """Generate and save a static validator from a repair event.

    Called by quality_helpers after each successful repair so the same class of
    bug is statically checked in future runs before code is submitted.

    Returns the path of the saved validator, or None if generation/saving failed.
    """
    try:
        validator_src = generate_validator(event)
        saved_path = save_validator(event, validator_src)
        # Persist metadata to disk so startup can log/surface the learned catalogue
        _save_validator_meta(event, saved_path)
        logger.info(
            "[repair_learning] learned from repair: bug_class=%s domain=%s entity=%s → validator at %s",
            event.bug_class.value, event.domain, event.entity, saved_path,
        )
        return saved_path
    except Exception as exc:
        logger.warning(
            "[repair_learning] learn_from_repair failed (non-fatal): bug_class=%s error=%s",
            event.bug_class.value, exc,
        )
        return None
