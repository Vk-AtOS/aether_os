"""KAN-243: every build uses the rule packs by construction. One design token set per run becomes the generated app's
theme (CSS variables + Tailwind config, no hex or palette class in the templates), and every p05 model prompt carries the
run's design rules and frontend security rules."""
from __future__ import annotations

import asyncio
import re

import pytest

from aether_os.core.llm import client as llm_client
from aether_os.core.rulepacks import scan_project
from aether_os.core.rulepacks.color import parse_oklch_css, to_hex
from aether_os.core.rulepacks.spec_rules import MAX_RULES_CHARS
from aether_os.phases.p05_frontend import theme_tokens as tt
from aether_os.tests.test_p05_generated_frontend import build_frontend

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


class Recorder:
    def __init__(self, answer=""):
        self.prompts, self.answer = [], answer

    async def call(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.answer


@pytest.fixture
def model(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: rec)
    monkeypatch.setenv("ENVIRONMENT", "production")
    return rec


# ── one token set per run, written as the theme ──────────────────────────────

@pytest.mark.parametrize("data,domain,site", [
    ({}, "ecommerce", "ecommerce"), ({}, "crm", "saas_dashboard"), ({}, "healthcare", "booking"),
    ({"app_shape": "website"}, "crm", "landing"), ({"site_type": "blog"}, "crm", "content"),
    ({"app_shape": "no-such-shape"}, "hrm", "internal_tool"),
])
def test_the_run_site_type_comes_from_the_spec_shape_then_the_domain(data, domain, site):
    assert tt.site_type_for(data, domain) == site


def test_moods_come_from_the_description_then_density_then_domain():
    assert tt.moods_for({"raw_input": "A calm, friendly booking site"}, "healthcare", "compact") == \
        ["calm", "friendly", "professional", "medical"]
    assert tt.moods_for({}, "fintech") == ["finance"]


@pytest.mark.parametrize("domain", ["crm", "healthcare"])
def test_generated_frontend_theme_is_the_run_tokens_and_templates_use_only_tokens(tmp_path, monkeypatch, domain):
    root = build_frontend(tmp_path, domain, monkeypatch, project_name="Juniper")
    css = (root / "src" / "index.css").read_text()
    cfg = (root / "tailwind.config.js").read_text()
    assert css.startswith("@import url('https://fonts.googleapis.com/css2?") and "--background:" in css and ".dark {" in css
    assert "var(--primary)" in cfg and "var(--font-heading)" in cfg and not _HEX.search(cfg)
    primary = parse_oklch_css(re.search(r"--primary: (oklch\([^)]*\))", css).group(1))
    assert f'content="{to_hex(primary)}"' in (root / "index.html").read_text()          # browser UI color = token
    assert f"Design tokens for Juniper ({tt.site_type_for({}, domain)})" in css
    # The templates reference tokens only: no hex color (DES-001) and no raw palette class (DES-002) anywhere.
    design = [f for f in scan_project(root, packs=("design",)).findings if f.rule_id in ("DES-001", "DES-002")]
    assert design == [], [(f.file, f.message) for f in design]


def test_tokens_are_generated_once_per_run_and_shared_by_the_page_writers(tmp_path, monkeypatch):
    calls = []
    real = tt.generate_tokens
    monkeypatch.setattr(tt, "generate_tokens", lambda *a, **k: calls.append(a) or real(*a, **k))
    build_frontend(tmp_path, "crm", monkeypatch)
    assert len(calls) == 1 and calls[0][0] == "saas_dashboard"


# ── the rules reach every model code-writing prompt ──────────────────────────

def _assert_rules(prompt: str, design: bool = True):
    assert "SECURITY RULES" in prompt
    if design:
        assert "DESIGN RULES" in prompt and "SEC-015" in prompt and "bg-background" in prompt
        assert not re.search(r"accent=\w+-\d00|gradient=from-", prompt)   # the old per-domain palette hints


def test_page_prompts_carry_the_design_and_security_rules_bounded(model):
    from aether_os.phases.p05_frontend import llm_page_writer as w
    tt.build_run_theme({"raw_input": "patients upload their scans"}, "Clinic", "healthcare")
    tokens = tt.current_theme().prompt_tokens()
    ent = {"table": "patients", "name": "Patient", "fields": [{"name": "name", "type": "string"}]}
    asyncio.run(w.write_entity_page_checked(ent, {}, "Clinic", "healthcare", "x", None, tokens))
    asyncio.run(w.write_dashboard_checked("healthcare", [ent], "Clinic", "x", None, tokens))
    asyncio.run(w.write_portal_home_checked("healthcare", "Clinic", "x", tokens))
    assert len(model.prompts) == 3
    for p in model.prompts:
        _assert_rules(p)
    rules = tt.page_rules_block()
    assert len(rules) <= MAX_RULES_CHARS and "booking" in rules.split("\n")[0]


def test_widget_prompt_carries_the_rules(model):
    from aether_os.phases.p05_frontend import helpers
    asyncio.run(helpers._generate_domain_component("crm", [{"table": "leads", "columns": ["id", "name"]}], "Deals", ""))
    _assert_rules(model.prompts[-1])
    assert "Glassmorphism" not in model.prompts[-1] and "gradient orb" not in model.prompts[-1]


