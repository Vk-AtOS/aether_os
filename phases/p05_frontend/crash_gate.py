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
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# TS2304/TS2552 cannot find name; TS2339/TS2551 property does not exist on type; TS2741 required prop missing;
# TS2349 expression is not callable.
CRASH_CODES = frozenset({"TS2304", "TS2552", "TS2339", "TS2551", "TS2741", "TS2349"})
_TSC_LINE = re.compile(r"^(src/[^\s(]+\.tsx?)\(\d+,\d+\): error (TS\d+): (.*)$")


def _replaceable(rel: str) -> bool:
    """Model-written surfaces that have a template twin: admin entity pages and the dashboard widget."""
    p = Path(rel)
    return (p.parent.as_posix() == "src/pages" and p.stem.endswith("Page") and p.stem != "Page") or (
        rel == "src/components/DomainWidget.tsx")


def crashing_files(tsc_lines: List[str]) -> Dict[str, List[str]]:
    """{relative path: messages} for replaceable files with at least one crash-class tsc error."""
    out: Dict[str, List[str]] = {}
    for line in tsc_lines:
        m = _TSC_LINE.match(line.strip())
        if m and m.group(2) in CRASH_CODES and _replaceable(m.group(1)):
            out.setdefault(m.group(1), []).append(f"{m.group(2)}: {m.group(3)[:160]}")
    return out


def _template_for(rel: str, *, domain_ir: Any, entities: List[dict], route_map: Dict[str, str],
                  domain: str) -> Optional[str]:
    stem = Path(rel).stem
    if stem == "DomainWidget":
        from aether_os.phases.p05_frontend.dashboard_stats import fallback_widget
        return fallback_widget(domain, entities)[1]
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
                           domain: str = "") -> List[str]:
    """Rewrite each crashing model-written page from its template. Returns the replaced relative paths."""
    replaced: List[str] = []
    for rel, msgs in crashing_files(tsc_lines).items():
        try:
            code = _template_for(rel, domain_ir=domain_ir, entities=entities or [], route_map=route_map or {},
                                 domain=domain)
        except Exception as e:
            logger.warning("p05 crash gate: no template for %s: %s", rel, e)
            continue
        if not code:
            logger.warning("p05 crash gate: %s would crash (%s) but has no template twin", rel, msgs[0])
            continue
        (frontend_dir / rel).write_text(code)
        replaced.append(rel)
        logger.warning("p05 crash gate: replaced %s with its template (%d crash-class error(s); first: %s)",
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
                         domain: str = "") -> List[str]:
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
                                  route_map=route_map or {}, domain=domain)
