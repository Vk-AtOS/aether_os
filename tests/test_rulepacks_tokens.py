"""KAN-243 rule packs: WCAG color math and the deterministic design-token generator."""
import re

import pytest

from aether_os.core.rulepacks import color as C
from aether_os.core.rulepacks import design_prompt_rules, generate_tokens, security_prompt_rules
from aether_os.core.rulepacks.design_catalog import SITE_TYPES, canonical_site_type
from aether_os.core.rulepacks.design_tokens import PAIRS
from aether_os.core.rulepacks.security_rules import CORE, FEATURES, detect_features
from aether_os.tests.rulepacks_fixtures import write_project


def test_wcag_contrast_matches_known_values():
    assert C.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert C.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert C.contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the classic AA-passing grey
    assert C.contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)  # and the one that fails
    assert C.relative_luminance((1.0, 1.0, 1.0)) == pytest.approx(1.0)


def test_oklch_round_trip_and_gamut_clamp():
    for hexv in ("#2a7f8f", "#ff6600", "#123456", "#fafafa"):
        rgb = C.parse_hex(hexv)
        assert C.to_hex(C.oklch_to_srgb(C.srgb_to_oklch(rgb))) == hexv
    out = C.oklch_to_srgb((0.7, 0.5, 140))  # far outside sRGB: chroma is reduced, channels stay in range
    assert all(0.0 <= c <= 1.0 for c in out)


def test_fit_contrast_moves_a_failing_color_until_it_passes():
    fixed = C.fit_contrast(C.parse_hex("#a0a0a0"), C.WHITE, 4.5)
    assert C.contrast_ratio(fixed, C.WHITE) >= 4.5


@pytest.mark.parametrize("site", SITE_TYPES)
@pytest.mark.parametrize("primary", [None, "#ffdd00", "#2a7f8f", "#ffffff", "#000000", "#7c3aed"])
@pytest.mark.parametrize("moods", [[], ["calm"], ["bold", "playful"], ["minimal"], ["luxury"]])
def test_no_token_pair_below_wcag_aa(site, primary, moods):
    t = generate_tokens(site, "Brand", moods, primary)
    assert t.failing_pairs() == []


def test_a_low_contrast_brand_color_is_adjusted_and_logged():
    t = generate_tokens("landing", "Sunny", primary="#ffdd00")  # white text on yellow is ~1.4:1
    assert C.contrast_ratio(t.light["primary-foreground"], t.light["primary"]) >= 4.5
    assert any("primary" in a for a in t.adjustments)


def test_emitted_css_values_still_pass_after_rounding():
    t = generate_tokens("booking", "Juniper Dental", ["calm"], "#2a7f8f")
    css = t.to_css()
    root, dark = css.split(".dark {")
    for block in (root, dark):
        vals = dict(re.findall(r"--([a-z0-9-]+): (oklch\([^)]*\));", block))
        for fg, bg, mn in PAIRS:
            assert C.contrast_ratio(C.parse_oklch_css(vals[fg]), C.parse_oklch_css(vals[bg])) >= mn, (fg, bg)


def test_tokens_are_deterministic_and_use_shadcn_names():
    a = generate_tokens("saas", "Ledgerly", ["trust"])
    b = generate_tokens("saas", "Ledgerly", ["trust"])
    assert a.to_css() == b.to_css() and a.to_tailwind() == b.to_tailwind()
    css = a.to_css()
    for var in ("--background", "--foreground", "--primary", "--primary-foreground", "--muted", "--accent",
                "--destructive", "--border", "--ring", "--radius", "--input", "--card", "--chart-1"):
        assert f"{var}:" in css
    assert ":root {" in css and ".dark {" in css and "prefers-reduced-motion" in css
    assert '"primary-foreground": "var(--primary-foreground)"' in a.to_tailwind()


def test_spacing_is_on_a_4px_grid_and_type_scale_grows():
    t = generate_tokens("content", "Field Notes")
    assert all(round(float(v.rstrip("rem")) * 16) % 4 == 0 for v in t.spacing.values())
    sizes = [float(v["size"].rstrip("rem")) for k, v in t.type_scale.items() if not v["size"].startswith("clamp")]
    assert sizes == sorted(sizes) and t.type_scale["base"]["size"] == "1.125rem"  # content sites read at 18px


def test_fonts_avoid_generic_defaults_except_internal_tools():
    seen = set()
    for site in SITE_TYPES:
        for name in ("a", "b", "c", "d", "e"):
            f = generate_tokens(site, name).fonts
            if site != "internal_tool":
                assert {f.heading, f.body} & {"Inter", "Roboto", "Arial"} == set()
            seen.add((f.heading, f.body))
    assert len(seen) >= 6  # different site types do not collapse to one pair
    url = generate_tokens("landing", "Nova").font_import_url()
    assert url.startswith("https://fonts.googleapis.com/css2?") and url.endswith("display=swap")
    assert all(len(w.split(";")) <= 4 for w in re.findall(r"wght@([\d;]+)", url))


def test_site_type_aliases_and_unknown_type():
    assert canonical_site_type("E-commerce") == "ecommerce"
    assert canonical_site_type("blog") == "content"
    assert canonical_site_type("Agent chat") == "agent_chat"
    with pytest.raises(ValueError):
        generate_tokens("spaceship")
    with pytest.raises(ValueError):
        generate_tokens("landing", primary="blue")


@pytest.mark.parametrize("site", SITE_TYPES)
def test_design_prompt_pack_is_compact_and_complete(site):
    text = design_prompt_rules(site, generate_tokens(site, "Brand"))
    assert len(text) / 4 <= 1200  # ~4 characters per token
    assert re.search(r"^1\. ", text, re.M)
    for must in ("loading", "empty", "error", "aria-label", "Motion budget", "gradient", "lorem ipsum"):
        assert must in text


def test_security_prompt_pack_core_plus_selected_modules():
    core = security_prompt_rules()
    assert core.count("\n") == len(CORE)
    full = security_prompt_rules(list(FEATURES))
    assert "DOMPurify" in full and "algorithms=" in full and "non-root" in full and "allow-list" in full
    assert "DOMPurify" not in security_prompt_rules(["fastapi"])
    assert len(full) / 4 <= 1300
    with pytest.raises(ValueError):
        security_prompt_rules(["cobol"])


def test_detect_features_reads_the_stack(tmp_path):
    feats = detect_features(write_project(tmp_path))
    assert {"fastapi", "sqlalchemy", "jwt-auth", "react", "docker"} <= set(feats)
    assert "llm-agent" not in feats
