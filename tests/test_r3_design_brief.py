"""KAN-176/188: the frontend look comes from a model-written design brief (fake model + fixtures here), is validated, falls
back to the token system, and the per-domain lookup tables are gone."""
import asyncio
import json
from pathlib import Path

import pytest

from aether_os.phases.p05_frontend import design_brief as db
from aether_os.tests.test_p05_generated_frontend import ENTITIES, build_frontend

FIXTURES = Path(__file__).parent / "fixtures" / "design_briefs"


class FakeLLM:
    """Answers with the fixture whose name appears in the prompt's 'Domain:' line; counts calls."""
    def __init__(self, answer=None):
        self.prompts, self.answer = [], answer

    async def call(self, prompt, **kw):
        self.prompts.append(prompt)
        if self.answer is not None:
            return self.answer
        domain = prompt.split("Domain:")[1].split("\n")[0].strip()
        return "Here is the brief:\n" + (FIXTURES / f"{domain}.json").read_text()


def _brief(domain):
    return asyncio.run(db.get_design_brief(FakeLLM(), "Demo", "a product", domain, ENTITIES))


def test_two_products_get_visibly_different_palettes_and_widgets(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    crm, health = _brief("crm"), _brief("healthcare")
    assert crm and health and crm["primary_hex"] != health["primary_hex"]
    assert crm["background_hex"] != health["background_hex"] and "LeadContact" in crm["widget_description"]
    assert "Patient" in health["widget_description"]


@pytest.mark.parametrize("answer", [
    "no json at all", "[1, 2]",
    json.dumps({**json.loads((FIXTURES / "crm.json").read_text()), "primary_hex": "red"}),                  # not #RRGGBB
    json.dumps({**json.loads((FIXTURES / "crm.json").read_text()), "primary_hex": "#fff; } body{x:1"}),    # CSS injection
    json.dumps({**json.loads((FIXTURES / "crm.json").read_text()), "density": "huge"}),
    json.dumps({**json.loads((FIXTURES / "crm.json").read_text()), "widget_description": "short"}),
])
def test_an_invalid_answer_gives_none_so_the_token_system_stays(monkeypatch, answer):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert asyncio.run(db.get_design_brief(FakeLLM(answer), "Demo", "x", "crm", ENTITIES)) is None


def test_no_model_in_test_mode_and_a_failing_model_give_none(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    llm = FakeLLM()
    assert asyncio.run(db.get_design_brief(llm, "Demo", "x", "crm", ENTITIES)) is None and not llm.prompts

    class Broken:
        async def call(self, *a, **k):
            raise RuntimeError("no key")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert asyncio.run(db.get_design_brief(Broken(), "Demo", "x", "crm", ENTITIES)) is None


def test_brand_scale_and_tailwind_override():
    scale = db.brand_scale("#4f46e5")
    assert scale[600] == "#4f46e5" and list(scale) == [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
    assert scale[50] > scale[900]                    # hex strings of light tints compare above dark shades
    from aether_os.phases.p05_frontend.code_writer import _generate_tailwind_config
    for theme in ("default", "neon"):
        original = _generate_tailwind_config(theme)
        css = db.apply_brand_to_tailwind(original, "#4f46e5")
        assert "600: '#4f46e5'" in css and css.count("brand: {") == 1 and len(css) > 200


def test_lookup_tables_are_gone():
    from aether_os.phases.p05_frontend import code_writer, helpers, prompts
    for mod in (prompts, helpers, code_writer):
        for name in ("DOMAIN_STAT_LABELS", "DOMAIN_COMPONENT_DESC", "DOMAIN_COLOR_HINTS"):
            assert not hasattr(mod, name), (mod.__name__, name)


def test_dashboard_card_labels_come_from_the_entities_not_from_a_per_domain_list(tmp_path, monkeypatch):
    # the old list labelled card i by position ("Cameras Online" on whatever entity came first)
    root = build_frontend(tmp_path, "security", monkeypatch)
    dash = (root / "src" / "pages" / "Dashboard.tsx").read_text()
    assert "Cameras Online" not in dash and "Active Alerts" not in dash and "Patients" in dash


@pytest.mark.parametrize("domain", ["crm", "healthcare"])
def test_generation_with_a_brief_themes_the_app_and_without_one_keeps_the_token_system(tmp_path, monkeypatch, domain):
    brief = json.loads((FIXTURES / f"{domain}.json").read_text())

    async def fake_brief(*a, **k):
        return db.validate_brief(brief)
    monkeypatch.setattr(db, "get_design_brief", fake_brief)
    root = build_frontend(tmp_path / "with", domain, monkeypatch)
    assert f"600: '{brief['primary_hex']}'" in (root / "tailwind.config.js").read_text()

    async def none(*a, **k):
        return None
    monkeypatch.setattr(db, "get_design_brief", none)
    plain = build_frontend(tmp_path / "without", domain, monkeypatch)
    assert f"600: '{brief['primary_hex']}'" not in (plain / "tailwind.config.js").read_text()
