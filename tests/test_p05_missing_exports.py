"""p05: model pages import named exports (TableHeader, CardDescription...) the existing local module lacks."""
from __future__ import annotations

import re
from pathlib import Path

from aether_os.phases.p05_frontend.code_writer_parts import part10, part11
from aether_os.phases.p05_frontend.missing_exports import parse_exports
from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules


def _tree(tmp_path: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


PAGE = ("import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/Table'\n"
        "import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'\n")


def test_parse_exports_forms():
    names, opaque = parse_exports(
        "export function A() {}\nexport const B = 1\nexport class C {}\nexport interface D {}\nexport type E = 1\n"
        "export { f, g as h, type i }\nexport default function K() {}\nexport * as ns from './x'\n")
    assert names >= {"A", "B", "C", "D", "E", "f", "h", "i", "default", "ns"} and "g" not in names and not opaque
    assert parse_exports("export * from './other'\n")[1] is True


def test_generator_table_and_card_get_the_shadcn_subcomponents(tmp_path):
    root = _tree(tmp_path, {
        "src/pages/UserPage.tsx": PAGE,
        "src/components/ui/Table.tsx": part11._generate_ui_table(),
        "src/components/ui/Card.tsx": part10._generate_ui_card()})
    before_table = (root / "src/components/ui/Table.tsx").read_text()
    ensure_local_modules(root)
    table = (root / "src/components/ui/Table.tsx").read_text()
    assert table.startswith(before_table.rstrip("\n"))  # append-only
    for n in ("TableHeader", "TableRow", "TableHead", "TableBody", "TableCell"):
        assert re.search(rf"export const {n}\b", table), n
    card = (root / "src/components/ui/Card.tsx").read_text()
    assert re.search(r"export const CardDescription\b", card)
    assert len(re.findall(r"export (?:const|function) Table\b", table)) == 1  # the generator's Table untouched
    names, _ = parse_exports(table)
    assert {"Table", "TableHeader", "TableCell"} <= names
    before = {p: p.read_text() for p in (root / "src").rglob("*.tsx")}
    assert ensure_local_modules(root) == []
    assert {p: p.read_text() for p in (root / "src").rglob("*.tsx")} == before  # idempotent


def test_helper_names_do_not_clash_with_the_file(tmp_path):
    root = _tree(tmp_path, {
        "src/pages/A.tsx": "import { Card, CardTitle } from '../components/ui/card'\n",
        "src/components/ui/card.tsx": "import * as React from 'react'\nconst cx = (s: string) => s\nexport const Card = () => <div className={cx('a')} />\n"})
    ensure_local_modules(root)
    text = (root / "src/components/ui/card.tsx").read_text()
    assert len(re.findall(r"\bconst cx\b", text)) == 1 and "cx__p_card" in text
    assert "export const Card = () =>" in text and re.search(r"export const CardTitle\b", text)
    assert text.count("import * as React") == 1


def test_unknown_names_get_forwarding_stub_and_unexported_locals_are_exported(tmp_path):
    root = _tree(tmp_path, {
        "src/pages/A.tsx": "import { Fancy, Hidden, type Opts } from '../components/widgets'\n",
        "src/components/widgets.tsx": "const Hidden = () => null\nexport const Other = () => null\n"})
    ensure_local_modules(root)
    text = (root / "src/components/widgets.tsx").read_text()
    assert "export const Fancy = (props: any)" in text and "export { Hidden }" in text and "export type Opts = any" in text
    assert "export const Other = () => null" in text


def test_export_star_module_is_left_alone(tmp_path):
    src = "export * from './inner'\n"
    root = _tree(tmp_path, {"src/pages/A.tsx": "import { TableHeader } from '../components/ui/Table'\n",
                            "src/components/ui/Table.tsx": src, "src/components/ui/inner.tsx": "export const TableHeader = 1\n"})
    ensure_local_modules(root)
    assert (root / "src/components/ui/Table.tsx").read_text() == src


def test_symlinked_target_outside_src_is_not_modified(tmp_path):
    outside = tmp_path / "outside.tsx"
    outside.write_text("export const Table = () => null\n")
    root = _tree(tmp_path / "fe", {"src/pages/A.tsx": "import { TableHeader } from '../components/ui/Table'\n"})
    (root / "src/components/ui").mkdir(parents=True)
    (root / "src/components/ui/Table.tsx").symlink_to(outside)
    ensure_local_modules(root)
    assert outside.read_text() == "export const Table = () => null\n"


def test_non_tsx_module_gets_no_jsx(tmp_path):
    root = _tree(tmp_path, {"src/pages/A.tsx": "import { helper, TableRow } from '../lib/stuff'\n",
                            "src/lib/stuff.ts": "export const other = 1\n"})
    ensure_local_modules(root)
    text = (root / "src/lib/stuff.ts").read_text()
    assert "<div" not in text and "export const helper" in text and "export const TableRow" in text


def test_a_name_the_module_imports_is_re_exported_not_redeclared(tmp_path):
    # Run da281716: a page imported Member from lib/api; api.ts imports Member (a type) from ../types, and p05 appended
    # `export type Member = any`, a second declaration of the imported binding (TS2440 failed the type-check).
    root = _tree(tmp_path, {
        "src/pages/MemberPage.tsx": "import { membersApi, Member } from '../lib/api'\nimport { cn } from '../lib/util'\n",
        "src/lib/api.ts": "import axios from 'axios'\nimport type { Team, Member } from '../types'\nexport const membersApi = {}\n",
        "src/lib/util.ts": "import { cn as join } from './cx'\nexport const x = 1\n",
        "src/lib/cx.ts": "export const cn = 1\n",
    })
    ensure_local_modules(root)
    api = (root / "src/lib/api.ts").read_text()
    assert "export type { Member }" in api and "Member = any" not in api
    util = (root / "src/lib/util.ts").read_text()
    assert "export const cn" in util      # the file binds `join`, not `cn`: a stub is still needed
