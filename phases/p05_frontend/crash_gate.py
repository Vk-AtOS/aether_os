"""P05: a model-written page that would crash at runtime is replaced by its template page before the app ships.

`vite build` does not type-check, so pages that throw on first render bundled fine and the click-through check found
them one acceptance run at a time: run 22 a DomainWidget rendering an unimported <ClipboardList>, run 24 a ProjectPage
calling `p.id.slice()` on a numeric id and a TaskPage using a Select prop shape that did not exist. build_loop already
runs `tsc --noEmit`; its leftover errors of the kinds that throw at runtime (an undefined name, a property or method
the value does not have, a missing required prop, calling a non-function) now decide: the file is rewritten from the
template generator, which is known to compile and render. Other type errors stay warnings, as before.
"""
from __future__ import annotations

import logging
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
