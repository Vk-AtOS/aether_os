"""
AetherOS — Code Pattern Library

Pre-built, tested code patterns for complex features.
The LLM selects which patterns to apply; the library injects working code.

Usage:
    from aether_os.phases.patterns import PatternSelector
    selector = PatternSelector(domain_ir)
    selected = selector.select()
    for pattern in selected:
        pattern.inject(project_dir)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Pattern definitions ────────────────────────────────────────────────────────

@dataclass
class Pattern:
    name: str
    description: str
    triggers: List[str]         # keywords in domain_ir that trigger this pattern
    files: Dict[str, str]       # relative_path → file_content
    requirements: List[str]     # pip packages to add to requirements.txt
    env_vars: List[str]         # .env vars to document

    def inject(self, project_dir: Path) -> List[str]:
        """Write pattern files into the project directory. Returns written file paths."""
        written: List[str] = []
        # Find the backend codegen directory
        backend_dirs = [
            project_dir / "p04_backend" / "backend_codegen",
            project_dir / "p04_backend",
            project_dir / "p03_scaffolding",
        ]
        backend_dir = next((d for d in backend_dirs if d.exists()), project_dir)

        for rel_path, content in self.files.items():
            target = backend_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(str(target))
            logger.info("Pattern[%s]: wrote %s", self.name, rel_path)

        # Append requirements
        req_file = backend_dir / "requirements.txt"
        if req_file.exists() and self.requirements:
            existing = req_file.read_text()
            new_reqs = [r for r in self.requirements if r not in existing]
            if new_reqs:
                req_file.write_text(existing.rstrip() + "\n" + "\n".join(new_reqs) + "\n")

        return written


# ── Pattern registry ──────────────────────────────────────────────────────────

def _websocket_pattern() -> Pattern:
    from aether_os.phases.patterns.websocket import WEBSOCKET_CODE, WEBSOCKET_REQUIREMENTS
    return Pattern(
        name="websocket",
        description="WebSocket real-time connection manager with room-based broadcasting",
        triggers=["real-time", "realtime", "chat", "live", "websocket", "ws", "notification", "broadcast"],
        files={"src/routers/ws.py": WEBSOCKET_CODE},
        requirements=WEBSOCKET_REQUIREMENTS,
        env_vars=[],
    )


def _file_upload_pattern() -> Pattern:
    from aether_os.phases.patterns.file_upload import FILE_UPLOAD_CODE, FILE_UPLOAD_REQUIREMENTS
    return Pattern(
        name="file_upload",
        description="Multipart file upload with local disk storage and S3-compatible API",
        triggers=["upload", "file", "attachment", "image", "document", "media", "photo", "pdf"],
        files={"src/routers/uploads.py": FILE_UPLOAD_CODE},
        requirements=FILE_UPLOAD_REQUIREMENTS,
        env_vars=["UPLOAD_DIR=/tmp/uploads", "MAX_UPLOAD_MB=10"],
    )


def _stripe_pattern() -> Pattern:
    from aether_os.phases.patterns.stripe import STRIPE_CODE, STRIPE_REQUIREMENTS
    return Pattern(
        name="stripe",
        description="Stripe checkout session, webhook handling, and subscription management",
        triggers=["payment", "stripe", "billing", "subscription", "checkout", "invoice", "credit card"],
        files={"src/routers/billing.py": STRIPE_CODE},
        requirements=STRIPE_REQUIREMENTS,
        env_vars=["STRIPE_SECRET_KEY=sk_test_...", "STRIPE_WEBHOOK_SECRET=whsec_..."],
    )


def _rbac_pattern() -> Pattern:
    from aether_os.phases.patterns.rbac import RBAC_CODE
    return Pattern(
        name="rbac",
        description="Role-based access control middleware with role hierarchy enforcement",
        triggers=["role", "permission", "rbac", "admin", "access control", "privilege", "authorization"],
        files={"src/middleware/rbac.py": RBAC_CODE},
        requirements=[],
        env_vars=[],
    )


_ALL_PATTERN_FACTORIES = [
    _websocket_pattern,
    _file_upload_pattern,
    _stripe_pattern,
    _rbac_pattern,
]


# ── Pattern selector ──────────────────────────────────────────────────────────

class PatternSelector:
    """Selects applicable patterns from the library based on domain_ir content."""

    def __init__(self, domain_ir: Optional[Dict[str, Any]] = None):
        self._ir = domain_ir or {}

    def _ir_text(self) -> str:
        """Flatten domain_ir to searchable text."""
        parts = []
        for key, val in self._ir.items():
            if isinstance(val, str):
                parts.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        parts.extend(str(v) for v in item.values())
                    else:
                        parts.append(str(item))
        return " ".join(parts).lower()

    def select(self) -> List[Pattern]:
        """Return patterns whose triggers match the domain IR content."""
        text = self._ir_text()
        selected: List[Pattern] = []
        for factory in _ALL_PATTERN_FACTORIES:
            try:
                pattern = factory()
                if any(trigger in text for trigger in pattern.triggers):
                    selected.append(pattern)
                    logger.info("PatternSelector: selected '%s' (trigger match)", pattern.name)
            except Exception as exc:
                logger.warning("PatternSelector: could not load pattern factory %s: %s", factory.__name__, exc)
        return selected

    def apply_all(self, project_dir: Path) -> Dict[str, List[str]]:
        """Select and inject all matching patterns. Returns {pattern_name: [written_files]}."""
        results: Dict[str, List[str]] = {}
        for pattern in self.select():
            try:
                written = pattern.inject(project_dir)
                results[pattern.name] = written
            except Exception as exc:
                logger.warning("PatternSelector: inject failed for '%s': %s", pattern.name, exc)
        return results
