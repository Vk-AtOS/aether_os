"""KAN-174/KAN-109: imports of packages that do not exist stay out of the pipeline."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEAD = re.compile(r"^\s*(from|import)\s+(src\.notifications|aether_os\.phases\.p15_change_requests)", re.M)


def test_no_imports_of_missing_packages():
    hits = [str(p.relative_to(ROOT)) for d in ("core", "phases", "stages", "orchestrator", "gateway")
            for p in (ROOT / d).rglob("*.py") if DEAD.search(p.read_text(errors="ignore"))]
    assert hits == []
