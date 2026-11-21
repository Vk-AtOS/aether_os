"""P05 Frontend: declare the npm packages model-written pages import but package.json lacks.

The model reaches for `date-fns`, `dayjs`... that the generated package.json never listed, and `vite build` dies
with "failed to resolve import". Packages on a small pinned allowlist are added; anything else is NOT added
(supply chain: a model-invented or typosquatted name must not reach `npm install`) and logged, so the build fails
visibly instead of silently installing arbitrary code.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from aether_os.phases.p05_frontend.code_writer_parts.part01 import generate_package_json
from aether_os.phases.p05_frontend.missing_modules import _DYN_RE, _FROM_RE, _SIDE_RE, _SRC_EXT

logger = logging.getLogger(__name__)

# Extras beyond what generate_package_json already pins; all work with React 18 / vite 6 / TS 5.
_EXTRA_ALLOWED = {"date-fns": "^4.1.0", "dayjs": "^1.11.13"}
_PKG_NAME_RE = re.compile(r"^(?:@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*$")


def allowed_packages() -> dict[str, str]:
    """name -> pinned range: the generated project's own dependencies plus the extras above."""
    return {**json.loads(generate_package_json("x"))["dependencies"], **_EXTRA_ALLOWED}


def _package_name(spec: str) -> str | None:
    if spec.startswith((".", "/", "@/", "~/", "node:", "virtual:", "data:", "http")):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return name if _PKG_NAME_RE.match(name) else None


def imported_packages(src: Path) -> set[str]:
    found: set[str] = set()
    for f in sorted(src.rglob("*")):
        if f.suffix not in _SRC_EXT or not f.is_file() or "node_modules" in f.parts:
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError as exc:
            logger.warning("p05 npm_deps: read %s failed: %s", f, exc)
            continue
        for rx in (_FROM_RE, _SIDE_RE, _DYN_RE):
            for m in rx.finditer(text):
                name = _package_name(m.group("spec"))
                if name:
                    found.add(name)
    return found


def ensure_npm_deps(frontend_dir: Path) -> list[str]:
    """Add allowlisted imported-but-undeclared packages to package.json. Returns the names added."""
    src, pkg_file = frontend_dir / "src", frontend_dir / "package.json"
    if not src.is_dir() or not pkg_file.is_file():
        return []
    try:
        pkg = json.loads(pkg_file.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("p05 npm_deps: cannot read package.json: %s", exc)
        return []
    declared = {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}
    allowed, added = allowed_packages(), []
    for name in sorted(imported_packages(src) - set(declared)):
        if name in allowed:
            pkg.setdefault("dependencies", {})[name] = allowed[name]
            added.append(name)
        else:
            logger.warning("p05 npm_deps: src imports %r which is not in package.json and not on the allowlist; "
                           "not added (the build will fail on it)", name)
    if added:
        pkg["dependencies"] = dict(sorted(pkg["dependencies"].items()))
        pkg_file.write_text(json.dumps(pkg, indent=2) + "\n")
        logger.info("p05 npm_deps: added %s to package.json", added)
    return added
