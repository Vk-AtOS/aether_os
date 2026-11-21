"""p05: DomainWidget is written as typed .tsx; Input/Textarea primitives accept `error`."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aether_os.phases.p05_frontend import domain_assembler
from aether_os.phases.p05_frontend.ui_primitives import UI_PRIMITIVES


def test_domain_widget_is_written_as_tsx(tmp_path):
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    written: list[Path] = []

    async def gen(*a, **k):
        return "export default function DomainWidget() { return <div /> }"

    async def run():
        return await domain_assembler.generate_domain_widget(
            src_dir=src, domain="x", entities=[], project_name="p", mem="", primary_hex="", secondary_hex="",
            background_hex="", surface_hex="", font_pairing="", border_radius="", density="",
            phase_start=asyncio.get_running_loop().time(), phase_timeout=1e9,
            generate_domain_component_fn=gen, write_with_guard_fn=lambda p, t: written.append(p))

    assert asyncio.run(run()) is True
    assert [p.name for p in written] == ["DomainWidget.tsx"]


def test_input_and_textarea_declare_error_prop():
    for name in ("input", "textarea"):
        text, _ = UI_PRIMITIVES[name]
        assert "error?: string" in text and "{error && " in text
