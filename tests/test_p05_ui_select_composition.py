"""Production run 24 (23 Nov 2026): the model-written TaskPage used the shadcn composition <Select><SelectTrigger>..
<SelectContent><SelectItem/>..</Select>, but the generated ui/Select.tsx was options-driven only: `options.length` on
undefined crashed the page as soon as "New Task" opened the form."""
from aether_os.phases.p05_frontend.code_writer_parts.part11 import _generate_ui_select
from aether_os.phases.p05_frontend.missing_exports import parse_exports


def test_select_without_options_wraps_its_children_before_touching_options():
    src = _generate_ui_select()
    guard = src.index("if (!Array.isArray(options)) {")
    assert guard < src.index("const showSearch = options.length")
    assert "{children}" in src[guard:src.index("const showSearch = options.length")]


def test_select_exports_the_shadcn_family_itself():
    names, opaque = parse_exports(_generate_ui_select())
    assert not opaque
    assert {"Select", "SelectTrigger", "SelectValue", "SelectContent", "SelectItem", "SelectGroup", "SelectLabel"} <= names


def test_empty_and_numeric_item_values_are_safe_for_radix():
    src = _generate_ui_select()
    assert "const toItemValue = (v: unknown) => (v === '' || v === null || v === undefined ? NONE : String(v))" in src
    assert "onValueChange?.(v === NONE ? '' : v)" in src
