"""KAN-243 rule packs: the design linter. Each rule has a positive and a near-miss negative case."""
import pytest

from aether_os.tests import rulepacks_fixtures as F

PAGE = "frontend/src/pages/TasksPage.tsx"
COMP = "frontend/src/components/Hero.tsx"


def comp(body: str) -> dict:
    return {COMP: f"export function Hero() {{\n  return (\n    {body}\n  );\n}}\n"}


def ids(tmp_path, overrides):
    return F.rule_ids(tmp_path, overrides, packs=("design",))


def test_clean_project_has_no_design_findings(tmp_path):
    assert ids(tmp_path, {}) == []


POSITIVE = [
    ("DES-001", comp('<div className="bg-[#ff6600] p-4">Hi</div>')),
    ("DES-001", comp("<div style={{ color: '#1e293b' }}>Hi</div>")),
    ("DES-001", {"frontend/src/extra.css": ".card { color: #333; }\n"}),
    ("DES-002", comp('<div className="bg-blue-500 text-white">Hi</div>')),
    ("DES-003", {"frontend/src/extra.css": "h1 { font-family: 'Poppins', sans-serif; }\np { font-family: Lato; }\n"}),
    ("DES-004", comp('<div className="p-[13px]">Hi</div>')),
    ("DES-005", comp('<img src="/hero.png" />')),
    ("DES-006", comp('<button onClick={() => close()}><XIcon className="h-4 w-4" /></button>')),
    ("DES-006", comp('<Button size="icon" />')),
    ("DES-007", comp('<input placeholder="Email" />')),
    ("DES-007", comp('<Textarea placeholder="Notes" />')),
    ("DES-008", comp('<div onClick={() => open()}>Open</div>')),
    ("DES-009", {PAGE: "import { useQuery } from 'x';\nexport default function P() {\n  const { data } = useQuery({});\n"
                       "  return <ul>{data.map((d) => <li key={d.id}>{d.name}</li>)}</ul>;\n}\n"}),
    ("DES-010", comp('<h1 className="bg-gradient-to-r from-amber-700 to-orange-600 bg-clip-text text-transparent">Hi</h1>')),
    ("DES-011", comp('<section className="bg-gradient-to-r from-violet-600 to-pink-500">Hi</section>')),
    ("DES-012", comp("<p>Lorem ipsum dolor sit amet</p>")),
    ("DES-012", comp("<p>Signed, John Doe</p>")),
    ("DES-013", comp("<h2>Revolutionize your workflow</h2>")),
    ("DES-014", comp('<input aria-label="q" className="outline-none" />')),
    ("DES-015", comp('<div><span className="animate-bounce">a</span><span className="animate-ping">b</span>'
                     '<span className="animate-fade">c</span><span className="animate-wiggle">d</span></div>')),
    ("DES-016", {"frontend/index.html": "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width\"></head></html>"}),
    ("DES-016", {"frontend/index.html": '<html lang="en"><head><meta name="viewport" content="width=device-width, user-scalable=no"></head></html>'}),
]


@pytest.mark.parametrize("rule,overrides", POSITIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(POSITIVE)])
def test_rule_fires(tmp_path, rule, overrides):
    assert rule in ids(tmp_path, overrides)


NEGATIVE = [
    ("DES-001", comp('<a href="#add">Jump to add</a>')),                          # an anchor, not a color
    ("DES-001", {"frontend/src/theme.css": ":root { --brand: #ff6600; }\n"}),      # the token file may hold raw colors
    ("DES-003", {"frontend/src/extra.css": "code { font-family: 'JetBrains Mono', monospace; }\n"}),  # mono is extra
    ("DES-004", comp('<div className="p-[16px] top-[1px]">Hi</div>')),          # on the grid / hairline offset
    ("DES-005", comp('<img src="/divider.svg" alt="" />')),                       # decorative image
    ("DES-006", comp('<button><XIcon /><span className="sr-only">Close</span></button>')),
    ("DES-006", comp('<button aria-label="Close"><XIcon /></button>')),
    ("DES-006", comp("<Button>{t('save')}</Button>")),                            # an expression may be the label
    ("DES-006", {"frontend/src/components/ui/button.tsx": "export const Button = (props) => <button {...props} />;\n"}),
    ("DES-007", comp('<label>Email <input type="email" /></label>')),
    ("DES-007", comp('<input type="hidden" name="csrf" />')),
    ("DES-007", comp('<input aria-label="Search" />')),
    ("DES-008", comp('<div role="button" tabIndex={0} onClick={go} onKeyDown={onKey}>Go</div>')),
    ("DES-008", comp('<div className="fixed inset-0" aria-hidden="true" onClick={close} />')),
    ("DES-009", {"frontend/src/components/Widget.tsx": "const { data } = useQuery({});\n"}),  # not a page
    ("DES-010", comp('<h1 className="text-foreground">Hi</h1>')),
    ("DES-012", comp('<input aria-label="Name" placeholder="John Doe" />')),       # an input hint, not content
    ("DES-014", comp('<input aria-label="q" className="outline-none focus-visible:ring-2" />')),
    ("DES-015", comp('<div className="animate-spin" /><div className="animate-pulse" />')),  # spinner / skeleton
    ("DES-016", {}),
]


@pytest.mark.parametrize("rule,overrides", NEGATIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(NEGATIVE)])
def test_rule_stays_quiet(tmp_path, rule, overrides):
    assert rule not in ids(tmp_path, overrides)


def test_reduced_motion_fallback_is_required_when_animating(tmp_path):
    over = {"frontend/src/index.css": "body { margin: 0; }\n", **comp('<div className="animate-bounce">!</div>')}
    found = F.findings(tmp_path, over, packs=("design",))
    assert any(f.rule_id == "DES-015" and "reduced-motion" in f.message for f in found)


def test_findings_carry_file_line_and_fix_hint(tmp_path):
    f = next(x for x in F.findings(tmp_path, comp('<img src="/hero.png" />'), packs=("design",)) if x.rule_id == "DES-005")
    assert f.file == COMP and f.line == 3 and f.fix_hint and f.severity == "medium" and "<img" in f.snippet


def test_jsx_arrow_functions_do_not_break_tag_parsing(tmp_path):
    over = comp('<img onLoad={() => a > b && setOk(true)} src="/x.png" alt="Chart of sales" />')
    assert "DES-005" not in ids(tmp_path, over)
