"""Production run 21 (22 Nov 2026): model-written pages use the shadcn composition <Table><TableHeader>..</Table>, but
the generated ui/Table.tsx was data-driven only and spread its undefined `data` prop: "e is not iterable" on every page."""
from aether_os.phases.p05_frontend.code_writer_parts.part11 import _generate_ui_table


def test_table_renders_children_when_used_as_a_composition_wrapper():
    src = _generate_ui_table()
    guard = src.index("if (!columns) {")
    assert guard < src.index("[...rows]")              # the wrapper returns before any spread of data
    assert "{children}</table>" in src[guard:guard + 300]


def test_table_never_spreads_a_non_array_data_prop():
    src = _generate_ui_table()
    assert "Array.isArray(data) ? data : []" in src
    assert "[...data]" not in src and "data.length" not in src

