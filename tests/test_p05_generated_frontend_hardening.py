"""KAN-168 follow-up: what the generated frontend does with spec text, tokens, paths and lists.
Built with the real generators (no model, no npm); the real TypeScript compiler checks syntax."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from aether_os.tests.test_p05_generated_frontend import _tsc, build_frontend


def sources(root: Path):
    for f in sorted(root.rglob("*")):
        if f.is_file() and "node_modules" not in f.parts and f.suffix in (".ts", ".tsx", ".js", ".jsx", ".html", ".json", ".css", ".md", ""):
            yield f, f.read_text(errors="replace")


def tsc_syntax_errors(root: Path) -> list:
    tsc = _tsc()
    if not tsc:
        pytest.skip("typescript (tsc) is not available")
    out = subprocess.run([tsc, "--noEmit", "-p", str(root)], capture_output=True, text=True, timeout=240).stdout
    return [ln for ln in out.splitlines() if re.search(r"error TS(1\d{3}|2304|2552):", ln)]


EVIL = "Acme</title><script>alert(1)</script>\"'{x}`${y}\\"


@pytest.mark.parametrize("domain", ["saas", "crm"])
def test_project_name_cannot_inject_script_or_break_source(tmp_path, monkeypatch, domain):
    # The project name went raw into index.html (a script ran), JSON-LD, JSX text and JS strings.
    root = build_frontend(tmp_path, domain, monkeypatch, project_name=EVIL,
                          extra={"app_tagline": EVIL, "app_brand": {"tagline": EVIL, "headline": EVIL}})
    html = (root / "index.html").read_text()
    assert "<script>alert" not in html and html.count("<script") == 2          # the app's module + JSON-LD only
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(ld)["name"].startswith("Acme")
    json.loads((root / "package.json").read_text())
    for f, text in sources(root):
        assert "<script>alert" not in text and "</title><script" not in text, f
    assert tsc_syntax_errors(root) == []
