"""
ArchitectureGovernor — validates that generated code stays within the Domain IR contract.

Checks:
  - All entity names used in generated files appear in domain_ir.entities
  - All fields referenced in generated models appear in their entity's field list
  - No phantom entities (invented by LLM, not in IR)
  - Route naming follows /<entity_plural_lower>/ pattern from IR
"""
from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GovernorViolation:
    phase: str           # "p04_backend" | "p05_frontend"
    violation_type: str  # "phantom_entity" | "missing_field" | "wrong_route" | "unknown_field"
    entity_name: str
    detail: str
    severity: str        # "error" | "warning"


@dataclass
class GovernorReport:
    violations: list[GovernorViolation] = field(default_factory=list)
    entities_in_ir: list[str] = field(default_factory=list)
    entities_found_in_code: list[str] = field(default_factory=list)
    phantom_entities: list[str] = field(default_factory=list)    # in code but not in IR
    missing_entities: list[str] = field(default_factory=list)    # in IR but not in code


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_class_names(source: str) -> list[str]:
    """Return all top-level class names from Python source using ast.parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("architecture_governor: ast.parse failed: %s", exc)
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]


def _parse_base_class_names(source: str) -> dict[str, list[str]]:
    """Return {class_name: [base_names]} for all class defs."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("architecture_governor: ast.parse (bases) failed: %s", exc)
        return {}
    result: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            result[node.name] = bases
    return result


def _extract_string_assignments(source: str, attr: str) -> list[str]:
    """Extract string literal values assigned to `attr` anywhere in the source.

    E.g. ``__tablename__ = "users"`` → ["users"]
    """
    pattern = re.compile(
        rf'{re.escape(attr)}\s*=\s*["\']([^"\']+)["\']'
    )
    return pattern.findall(source)


def _extract_router_prefixes(source: str) -> list[str]:
    """Extract prefix strings from APIRouter(prefix="...") declarations."""
    pattern = re.compile(
        r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    return [m.strip("/") for m in pattern.findall(source)]


def _extract_decorator_routes(source: str) -> list[str]:
    """Extract path strings from @router.METHOD("...") / @app.METHOD("...") decorators."""
    pattern = re.compile(
        r'@(?:app|router)\.\w+\(["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    return pattern.findall(source)


def _normalise(name: str) -> str:
    """Lower-case, strip underscores/hyphens for fuzzy entity matching."""
    return re.sub(r"[_\-\s]+", "", name.lower())


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ArchitectureGovernor:
    """Validates generated code against the Domain IR entity contract."""

    def __init__(self, domain_ir: dict) -> None:
        """domain_ir is the dict from domain_ir.json — has 'entities' list."""
        self._ir = domain_ir
        entities: list[dict] = domain_ir.get("entities", [])

        # Canonical entity name set — uses "name" key (PascalCase in IR)
        self._entity_names: set[str] = {e["name"] for e in entities if e.get("name")}

        # Normalised lookup: lowercase-no-separators → canonical name
        self._norm_to_name: dict[str, str] = {
            _normalise(e["name"]): e["name"]
            for e in entities
            if e.get("name")
        }

        # Per-entity field set
        self._entity_fields: dict[str, set[str]] = {
            e["name"]: {f["name"] for f in e.get("fields", []) if f.get("name")}
            for e in entities
            if e.get("name")
        }

        # Table names → canonical entity name (for route matching)
        self._table_to_name: dict[str, str] = {}
        for e in entities:
            if e.get("table") and e.get("name"):
                self._table_to_name[e["table"].lower()] = e["name"]

    # ------------------------------------------------------------------ #
    # Public check methods
    # ------------------------------------------------------------------ #

    def check_backend_models(self, models_code: str) -> list[GovernorViolation]:
        """Parse models.py source, extract class names, compare to IR entities.

        SQLAlchemy model classes that inherit from Base/DeclarativeBase are
        assumed to be entity models. Each is checked against the IR.
        Fields (Column definitions) are extracted and validated.
        """
        if not models_code.strip():
            return []

        violations: list[GovernorViolation] = []
        class_bases = _parse_base_class_names(models_code)

        # Identify model classes: those that inherit Base-like classes
        _base_markers = {"Base", "DeclarativeBase", "SQLModel", "Model"}
        model_classes = [
            cls
            for cls, bases in class_bases.items()
            if any(b in _base_markers for b in bases)
        ]

        # Well-known non-entity helper classes to skip
        _skip_classes = {
            "Base", "TimestampMixin", "AuditMixin", "User", "Token",
            "TokenData", "OAuthAccount",
        }

        for cls_name in model_classes:
            if cls_name in _skip_classes:
                continue

            # Check if class name matches any IR entity (case-insensitive)
            canonical = self._norm_to_name.get(_normalise(cls_name))
            if canonical is None:
                violations.append(GovernorViolation(
                    phase="p04_backend",
                    violation_type="phantom_entity",
                    entity_name=cls_name,
                    detail=f"Model class '{cls_name}' has no matching entity in Domain IR",
                    severity="warning",
                ))
                continue

            # Check fields if we can find them
            ir_fields = self._entity_fields.get(canonical, set())
            if ir_fields:
                violations.extend(
                    self._check_model_fields(models_code, cls_name, canonical, ir_fields)
                )

        return violations

    def _check_model_fields(
        self,
        source: str,
        cls_name: str,
        canonical: str,
        ir_fields: set[str],
    ) -> list[GovernorViolation]:
        """Extract Column(...) assignments from a class body and check against IR fields."""
        violations: list[GovernorViolation] = []
        # Heuristic: find lines under the class definition that look like field assignments
        # Pattern: <identifier> = Column(...) or <identifier>: Mapped[...] = mapped_column(...)
        field_pattern = re.compile(
            r'^\s{4,}([a-z_][a-z0-9_]*)\s*(?::\s*\S+)?\s*=\s*(?:Column|mapped_column|relationship)\(',
            re.MULTILINE,
        )
        # Skip standard bookkeeping columns
        _auto_cols = {"id", "created_at", "updated_at", "deleted_at", "__tablename__"}

        for m in field_pattern.finditer(source):
            col_name = m.group(1)
            if col_name in _auto_cols:
                continue
            if col_name not in ir_fields:
                violations.append(GovernorViolation(
                    phase="p04_backend",
                    violation_type="unknown_field",
                    entity_name=canonical,
                    detail=(
                        f"Model '{cls_name}' has field '{col_name}' "
                        f"not in IR fields for '{canonical}': {sorted(ir_fields)}"
                    ),
                    severity="warning",
                ))
        return violations

    def check_backend_routes(self, crud_code: str) -> list[GovernorViolation]:
        """Check router prefixes match IR entity names (via table name lookup)."""
        if not crud_code.strip():
            return []

        violations: list[GovernorViolation] = []
        prefixes = _extract_router_prefixes(crud_code)

        for prefix in prefixes:
            # Strip leading slash, get base segment
            segment = prefix.split("/")[0].lower()
            if not segment or segment in ("auth", "system", "api", "health"):
                continue

            # Check if segment matches a known table name (plural or singular)
            matched = (
                segment in self._table_to_name
                or segment.rstrip("s") in self._table_to_name
                or (segment + "s") in self._table_to_name
            )
            if not matched:
                # Also try normalised entity name match
                norm_seg = _normalise(segment.rstrip("s"))
                matched = norm_seg in self._norm_to_name

            if not matched:
                violations.append(GovernorViolation(
                    phase="p04_backend",
                    violation_type="wrong_route",
                    entity_name=segment,
                    detail=(
                        f"Router prefix '/{prefix}' does not map to any IR entity "
                        f"(known tables: {sorted(self._table_to_name.keys())})"
                    ),
                    severity="warning",
                ))

        return violations

    def check_frontend_components(self, component_names: list[str]) -> list[GovernorViolation]:
        """Verify each generated component maps to an IR entity."""
        violations: list[GovernorViolation] = []

        # Component names are expected to be like "UserPage", "ProductPage", etc.
        # Strip known suffixes to get the entity name candidate
        _page_suffix = re.compile(r"(?:Page|List|Form|Table|Card|Detail|Edit|Create)$")

        for comp in component_names:
            base = _page_suffix.sub("", comp)
            if not base:
                continue
            # Skip well-known non-entity components
            if base in {"Dashboard", "Login", "NotFound", "Customer", "Admin",
                        "Landing", "Home", "Layout", "Error", "Toaster",
                        "Crud", "Data", "Domain", "Not", ""}:
                continue

            canonical = self._norm_to_name.get(_normalise(base))
            if canonical is None:
                violations.append(GovernorViolation(
                    phase="p05_frontend",
                    violation_type="phantom_entity",
                    entity_name=base,
                    detail=(
                        f"Frontend component '{comp}' (base='{base}') "
                        f"has no matching entity in Domain IR"
                    ),
                    severity="warning",
                ))

        return violations

    def generate_report(self, phase: str, code_artifacts: dict[str, str]) -> GovernorReport:
        """Run all applicable checks and return a GovernorReport.

        code_artifacts: {"models.py": content, "routers/crud.py": content, ...}
        """
        all_violations: list[GovernorViolation] = []

        models_code = code_artifacts.get("models.py", "")
        crud_code = code_artifacts.get("crud.py", "") or code_artifacts.get("routers/crud.py", "")

        if phase == "p04_backend":
            if models_code:
                all_violations.extend(self.check_backend_models(models_code))
            if crud_code:
                all_violations.extend(self.check_backend_routes(crud_code))

        # Determine which entity names were found in code
        entities_found: list[str] = []
        if models_code:
            class_names = _parse_class_names(models_code)
            for cls in class_names:
                canonical = self._norm_to_name.get(_normalise(cls))
                if canonical:
                    entities_found.append(canonical)

        entities_in_ir = sorted(self._entity_names)
        phantom = [
            v.entity_name for v in all_violations
            if v.violation_type == "phantom_entity"
        ]
        missing = [
            name for name in entities_in_ir
            if name not in entities_found
        ]

        return GovernorReport(
            violations=all_violations,
            entities_in_ir=entities_in_ir,
            entities_found_in_code=entities_found,
            phantom_entities=phantom,
            missing_entities=missing,
        )

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @classmethod
    def from_output_dir(cls, output_dir: Path) -> "ArchitectureGovernor | None":
        """Load domain_ir.json from output_dir. Returns None if not found.

        Searches in output_dir, its parent, and common subdirectories.
        """
        candidates = [
            output_dir / "domain_ir.json",
            output_dir.parent / "domain_ir.json",
            output_dir / "p02b_domain_ir" / "domain_ir.json",
            output_dir.parent / "p02b_domain_ir" / "domain_ir.json",
        ]
        for path in candidates:
            if path.is_file():
                try:
                    data = json.loads(path.read_text())
                    if data.get("entities"):
                        logger.debug(
                            "architecture_governor: loaded IR from %s (%d entities)",
                            path, len(data["entities"]),
                        )
                        return cls(data)
                except Exception as exc:
                    logger.warning("architecture_governor: failed to load %s: %s", path, exc)
        logger.debug("architecture_governor: no domain_ir.json found under %s", output_dir)
        return None
