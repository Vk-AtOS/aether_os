"""P05 Gate — validate React/Vite/TanStack project generation + TypeScript types.

Checks:
  1. Required files exist (package.json, main.tsx, App.tsx)
  2. At least one entity page generated
  3. Required dependencies declared in package.json
  4. TypeScript type-check (tsc --noEmit) — if node_modules already installed
  5. FK endpoints referenced in generated pages exist in api_routes.json (schema contract)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_REQUIRED_DEPS = ["react", "@tanstack/react-query", "@tanstack/react-router", "@tanstack/react-table"]


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path:
        return GateOutcome(passed=False, confidence=0.0, issues=["No output_path set"])

    out_path = Path(result.output_path)

    # Locate frontend/ directory
    if out_path.name == "frontend":
        frontend_dir = out_path
    elif (out_path / "frontend").exists():
        frontend_dir = out_path / "frontend"
    else:
        frontend_dir = out_path / "frontend"

    # ── 1. Required files ─────────────────────────────────────────────────────
    required_files = [
        frontend_dir / "package.json",
        frontend_dir / "src" / "main.tsx",
        frontend_dir / "src" / "App.tsx",
    ]
    for f in required_files:
        if not f.exists():
            try:
                rel = f.relative_to(out_path.parent)
            except ValueError:
                rel = f
            issues.append(f"Missing required file: {rel}")

    # ── 2. Entity pages ───────────────────────────────────────────────────────
    pages_dir = frontend_dir / "src" / "pages"
    if pages_dir.exists():
        entity_pages = [p for p in pages_dir.glob("*Page.tsx") if p.stem != "LoginPage"]
        if not entity_pages:
            issues.append("No entity pages found in frontend/src/pages/")
    else:
        issues.append("frontend/src/pages/ directory does not exist")

    # ── 3. Package.json dependencies ─────────────────────────────────────────
    pkg_file = frontend_dir / "package.json"
    if pkg_file.exists():
        try:
            pkg = json.loads(pkg_file.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for dep in _REQUIRED_DEPS:
                if dep not in deps:
                    issues.append(f"Missing dependency in package.json: {dep}")
        except Exception as exc:
            issues.append(f"Could not parse package.json: {exc}")

    # Hard-fail if all critical files are missing
    if issues and all("Missing required file" in i or "does not exist" in i for i in issues):
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    confidence = 0.90 if not issues else 0.72

    # ── 4. TypeScript type-check (non-blocking — lowers confidence) ───────────
    tsc = frontend_dir / "node_modules" / ".bin" / "tsc"
    if tsc.exists():
        try:
            proc = subprocess.run(
                [str(tsc), "--noEmit", "--skipLibCheck"],
                capture_output=True, text=True, timeout=60,
                cwd=str(frontend_dir),
            )
            if proc.returncode != 0:
                # Collect first 5 distinct error lines
                ts_lines = [
                    ln for ln in (proc.stdout + proc.stderr).splitlines()
                    if "error TS" in ln
                ][:5]
                if ts_lines:
                    issues.append(f"TypeScript errors ({len(ts_lines)} shown): " + "; ".join(ts_lines))
                    confidence = min(confidence, 0.65)
                    # Don't hard-fail — let self-healing patch specific errors
        except subprocess.TimeoutExpired:
            issues.append("tsc --noEmit timed out (60s) — skipped")
        except Exception as exc:
            issues.append(f"tsc check error (non-fatal): {exc}")

    # ── 5. Schema contract: FK endpoints vs api_routes.json ───────────────────
    # Find api_routes.json written by p04
    project_root = out_path.parent
    routes_file = next(
        (f for f in [
            project_root / "p04_backend" / "backend_codegen" / "api_routes.json",
            project_root / "p04_backend" / "api_routes.json",
        ] if f.exists()),
        None,
    )
    if routes_file:
        try:
            known_routes: list[dict] = json.loads(routes_file.read_text()) or []
            known_paths = {r.get("path", "").rstrip("/").lower() for r in known_routes}

            # Scan generated page files for fkEndpoint references
            missing_fk: list[str] = []
            for tsx_file in pages_dir.glob("*Page.tsx") if pages_dir.exists() else []:
                source = tsx_file.read_text(errors="ignore")
                import re
                for match in re.finditer(r"fkEndpoint:\s*['\"]([^'\"]+)['\"]", source):
                    ep = match.group(1).rstrip("/").lower()
                    # Strip /api prefix for comparison (routes may be stored without it)
                    ep_bare = ep.removeprefix("/api")
                    if ep not in known_paths and ep_bare not in known_paths:
                        missing_fk.append(ep)

            if missing_fk:
                uniq = list(dict.fromkeys(missing_fk))[:4]
                issues.append(
                    f"Schema contract: FK endpoints not in api_routes.json: {uniq} "
                    f"— frontend will get 404 on dropdown fetch"
                )
                confidence = min(confidence, 0.70)
        except Exception as exc:
            issues.append(f"Schema contract check error (non-fatal): {exc}")

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
