"""P05: a model-written page that would crash at runtime is replaced by its template page before the app ships.

`vite build` does not type-check, so pages that throw on first render bundled fine and the click-through check found
them one acceptance run at a time: run 22 a DomainWidget rendering an unimported <ClipboardList>, run 24 a ProjectPage
calling `p.id.slice()` on a numeric id and a TaskPage using a Select prop shape that did not exist. build_loop already
runs `tsc --noEmit`; its leftover errors of the kinds that throw at runtime (an undefined name, a property or method
the value does not have, a missing required prop, calling a non-function) now decide: the file is rewritten from the
template generator, which is known to compile and render. Other type errors stay warnings, as before.

`tsc --noEmit` alone is not enough: while ANY file fails to parse it reports only syntax errors and no type errors at
all. In run 27 a model-written customer/Home.tsx had a JSX syntax slip, so tsc never reported the ProjectPage's
undefined <AlertDialogFooter>, the gate saw nothing and the page crashed. per_file_diagnostics() asks the TypeScript
compiler for each file's own diagnostics, which it reports regardless of other files. The gate also runs after
s04's repair loop (which re-ran p05 and rebuilt without it).

KAN-255 / KAN-251: the gate covered only *Page files and DomainWidget, so a model-written Dashboard.tsx (run 909708e8:
syntax error) or customer Home.tsx shipped broken. Every model-written surface with a template twin (entity pages,
Dashboard, customer Home, DomainWidget) is now replaced when it has a syntax error or, in the final pass
(`all_errors=True`), any type error left after the repair rounds: the template is known to type-check. Any other file
with errors is not replaced; tsc still lists it, which fails the build instead of shipping it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# TS2304/TS2552 cannot find name; TS2339/TS2551 property does not exist on type; TS2741 required prop missing;
# TS2349 expression is not callable.
CRASH_CODES = frozenset({"TS2304", "TS2552", "TS2339", "TS2551", "TS2741", "TS2349"})
_TSC_LINE = re.compile(r"^(src/[^\s(]+\.tsx?)\(\d+,\d+\): error (TS\d+): (.*)$")
_SYNTAX_CODE = re.compile(r"^TS(?:1\d{3}|17\d{3})$")   # TS1xxx / TS17xxx: the file does not parse
_REPLACEABLE_FILES = ("src/components/DomainWidget.tsx", "src/pages/Dashboard.tsx", "src/pages/customer/Home.tsx")


def _replaceable(rel: str) -> bool:
    """Model-written surfaces that have a template twin: admin entity pages, the dashboard, its widget, customer home."""
    p = Path(rel)
    return (p.parent.as_posix() == "src/pages" and p.stem.endswith("Page") and p.stem != "Page") or (
        rel in _REPLACEABLE_FILES)


def crashing_files(tsc_lines: List[str], all_errors: bool = False) -> Dict[str, List[str]]:
    """{relative path: messages} for replaceable files with a syntax error or crash-class tsc error (any tsc error
    with all_errors)."""
    out: Dict[str, List[str]] = {}
    for line in tsc_lines:
        m = _TSC_LINE.match(line.strip())
        if m and (all_errors or m.group(2) in CRASH_CODES or _SYNTAX_CODE.match(m.group(2))) and _replaceable(m.group(1)):
            out.setdefault(m.group(1), []).append(f"{m.group(2)}: {m.group(3)[:160]}")
    return out


def _admin_prefix(frontend_dir: Path) -> str:
    """"/admin" in the dual-portal layout (App.tsx has an adminLayoutRoute), where every admin route lives under it."""
    try:
        return "/admin" if "adminLayoutRoute" in (frontend_dir / "src" / "App.tsx").read_text() else ""
    except OSError as e:
        logger.warning("p05 crash gate: cannot read App.tsx to find the route prefix: %s", e)
        return ""


def _project_name(frontend_dir: Path) -> str:
    """The run's project name from frontend_meta.json (beside the shipped copy), else a neutral title."""
    for meta in (frontend_dir.parent / "p05_frontend" / "frontend_meta.json", frontend_dir.parent / "frontend_meta.json"):
        try:
            return str(json.loads(meta.read_text()).get("project_name") or "Dashboard")
        except (OSError, ValueError) as e:
            logger.debug("p05 crash gate: no project name in %s: %s", meta, e)
    return "Dashboard"


def _dashboard_twin(frontend_dir: Path, entities: List[dict], domain: str) -> str:
    """The stats Dashboard (every number from /stats), with the DomainWidget wired back in when that file exists."""
    from aether_os.phases.p05_frontend.dashboard_stats import stats_dashboard_tsx
    code = stats_dashboard_tsx(entities, _project_name(frontend_dir), _admin_prefix(frontend_dir))
    if (frontend_dir / "src" / "components" / "DomainWidget.tsx").is_file():
        code = code.replace("import { useQuery }", "import DomainWidget from '../components/DomainWidget'\n"
                            "import { ErrorBoundary } from '../components/ErrorBoundary'\nimport { useQuery }", 1)
        code = code.replace("{/* DOMAIN_WIDGET_SLOT */}", '<div className="mt-8"><ErrorBoundary fallback={<></>}>'
                            '<DomainWidget /></ErrorBoundary></div>', 1)
    return code


def _home_twin(frontend_dir: Path, domain: str) -> str:
    """The customer portal Home the generator writes before the model gets a chance to replace it."""
    from aether_os.phases.p05_frontend.helpers import _generate_customer_portal
    with tempfile.TemporaryDirectory() as tmp:
        # The generator is `async` but never awaits; a worker thread gives it its own loop while the gate's runs.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _generate_customer_portal(
                domain, {}, {}, Path(tmp), project_name=_project_name(frontend_dir))).result()
        return (Path(tmp) / "customer" / "Home.tsx").read_text()


def _template_for(rel: str, *, domain_ir: Any, entities: List[dict], route_map: Dict[str, str],
                  domain: str, frontend_dir: Optional[Path] = None) -> Optional[str]:
    stem = Path(rel).stem
    if stem == "DomainWidget":
        from aether_os.phases.p05_frontend.dashboard_stats import fallback_widget
        return fallback_widget(domain, entities)[1]
    if rel == "src/pages/Dashboard.tsx" and frontend_dir is not None:
        return _dashboard_twin(frontend_dir, entities, domain)
    if rel == "src/pages/customer/Home.tsx" and frontend_dir is not None:
        return _home_twin(frontend_dir, domain)
    if stem == "Dashboard" or stem == "Home":
        return None
    name = stem[: -len("Page")]
    if domain_ir is not None and getattr(domain_ir, "entities", None):
        from aether_os.phases.p05_frontend.ir_generators import generate_ir_entity_page
        for ent in domain_ir.entities:
            if ent.name == name:
                return generate_ir_entity_page(ent)
    from aether_os.phases.p05_frontend.code_writer_parts.part09 import _generate_entity_page
    from aether_os.phases.p05_frontend.scaffold import to_pascal_case
    for ent in entities:
        if (ent.get("name") or to_pascal_case(ent.get("table", ""))) == name:
            return _generate_entity_page(ent, route_map)
    return None


def replace_crashing_pages(frontend_dir: Path, tsc_lines: List[str], *, domain_ir: Any = None,
                           entities: Optional[List[dict]] = None, route_map: Optional[Dict[str, str]] = None,
                           domain: str = "", all_errors: bool = False) -> List[str]:
    """Rewrite each crashing model-written file from its template. Returns the replaced relative paths."""
    replaced: List[str] = []
    for rel, msgs in crashing_files(tsc_lines, all_errors).items():
        try:
            code = _template_for(rel, domain_ir=domain_ir, entities=entities or [], route_map=route_map or {},
                                 domain=domain, frontend_dir=frontend_dir)
        except Exception as e:
            logger.warning("p05 crash gate: no template for %s: %s", rel, e)
            continue
        if not code:
            logger.warning("p05 crash gate: %s would crash (%s) but has no template twin", rel, msgs[0])
            continue
        target = frontend_dir / rel
        if not target.is_file():
            logger.warning("p05 crash gate: %s is reported by tsc but is not on disk", rel)
            continue
        if target.read_text() == code:
            logger.warning("p05 crash gate: %s is already its template and still fails (%s)", rel, msgs[0])
            continue   # not model output: replacing it again would change nothing
        target.write_text(code)
        replaced.append(rel)
        logger.warning("p05 crash gate: replaced %s with its template (%d error(s); first: %s)",
                       rel, len(msgs), msgs[0])
    return replaced


# Per-file syntactic + semantic diagnostics in tsc's line format, run with the project's own typescript package.
_PER_FILE_JS = r"""
const ts = require('typescript');
const path = require('path');
const host = { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} };
const cfg = ts.getParsedCommandLineOfConfigFile('tsconfig.json', {}, host);
const program = ts.createProgram(cfg.fileNames, cfg.options);
for (const sf of program.getSourceFiles()) {
  if (sf.isDeclarationFile || !sf.fileName.includes('/src/')) continue;
  for (const d of [...program.getSyntacticDiagnostics(sf), ...program.getSemanticDiagnostics(sf)]) {
    if (!d.file || d.start === undefined) continue;
    const { line, character } = d.file.getLineAndCharacterOfPosition(d.start);
    const rel = path.relative(process.cwd(), d.file.fileName).split(path.sep).join('/');
    console.log(`${rel}(${line + 1},${character + 1}): error TS${d.code}: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`);
  }
}
"""
_SCRIPT_NAME = ".aether_per_file_check.cjs"


async def per_file_diagnostics(frontend_dir: Path) -> List[str]:
    """Every file's own diagnostics, even when another file does not parse. [] when it cannot run (the caller still
    has the plain tsc lines)."""
    if os.environ.get("ENVIRONMENT") == "test":
        return []
    from aether_os.core.sandbox import phase_exec
    script = frontend_dir / _SCRIPT_NAME
    try:
        script.write_text(_PER_FILE_JS)
        res = await phase_exec.run(["node", _SCRIPT_NAME], cwd=frontend_dir, timeout=120, text=True)
        out = (res.stdout or "") + (res.stderr or "")
        return [ln.strip() for ln in out.splitlines() if " error TS" in ln]
    except Exception as e:
        logger.warning("p05 crash gate: per-file diagnostics failed, using tsc output only: %s", e)
        return []
    finally:
        try:
            script.unlink()
        except OSError as e:
            logger.warning("p05 crash gate: could not remove %s: %s", script, e)


def load_project_ir(frontend_dir: Path) -> Any:
    """The run's domain IR (project_dir/p02b_domain_ir/domain_ir.json, beside project_dir/frontend), or None."""
    path = frontend_dir.parent / "p02b_domain_ir" / "domain_ir.json"
    if not path.is_file():
        return None
    try:
        from aether_os.core.domain_ir import DomainIR
        return DomainIR.load(path)
    except Exception as e:
        logger.warning("p05 crash gate: cannot load %s: %s", path, e)
        return None


async def run_crash_gate(frontend_dir: Path, tsc_lines: List[str], *, domain_ir: Any = None,
                         entities: Optional[List[dict]] = None, route_map: Optional[Dict[str, str]] = None,
                         domain: str = "", all_errors: bool = True) -> List[str]:
    """Collect plain tsc lines + per-file diagnostics and replace every crashing model-written page. Callers outside
    p05 (s04 repair) pass nothing else: the IR, entities and domain are loaded from the project."""
    lines = list(dict.fromkeys([*tsc_lines, *await per_file_diagnostics(frontend_dir)]))
    if domain_ir is None:
        domain_ir = load_project_ir(frontend_dir)
    if entities is None and domain_ir is not None:
        from aether_os.phases.p05_frontend.ir_generators import ir_to_p05_entities
        entities = ir_to_p05_entities(domain_ir)
    domain = domain or getattr(domain_ir, "domain", "") or ""
    return replace_crashing_pages(frontend_dir, lines, domain_ir=domain_ir, entities=entities or [],
                                  route_map=route_map or {}, domain=domain, all_errors=all_errors)
