"""p05: model-written pages import shadcn-style primitives and local modules the generator never wrote."""
from __future__ import annotations

from pathlib import Path

from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules


def _tree(tmp_path: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


DASH = (
    "import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'\n"
    "import { Button } from '@/components/ui/button'\n"
    "export default function Dashboard() { return <Card><CardHeader><CardTitle>x</CardTitle></CardHeader>"
    "<CardContent><Button>go</Button></CardContent></Card> }\n"
)


def test_ui_primitives_written_with_used_exports(tmp_path):
    root = _tree(tmp_path, {"src/pages/Dashboard.tsx": DASH})
    written = ensure_local_modules(root)
    assert "src/components/ui/card.tsx" in written and "src/components/ui/button.tsx" in written
    card = (root / "src/components/ui/card.tsx").read_text()
    for n in ("Card", "CardHeader", "CardTitle", "CardContent"):
        assert f"export const {n} " in card
    assert "export const Button " in (root / "src/components/ui/button.tsx").read_text()
    assert ensure_local_modules(root) == []  # idempotent


def test_unknown_named_import_gets_forwarding_component(tmp_path):
    root = _tree(tmp_path, {"src/pages/A.tsx": "import { Card, Fancy } from '@/components/ui/card'\nimport { Widget, helper, type Opts } from './x/widget'\n"})
    ensure_local_modules(root)
    assert "export const Fancy = (props: any) => <div {...props} />" in (root / "src/components/ui/card.tsx").read_text()
    stub = (root / "src/pages/x/widget.tsx").read_text()
    assert "export const Widget" in stub and "export const helper" in stub and "export type Opts" in stub


def test_existing_files_not_overwritten_and_cn_util(tmp_path):
    root = _tree(tmp_path, {
        "src/pages/Dashboard.tsx": DASH + "import { cn } from '@/lib/utils'\n",
        "src/components/ui/card.tsx": "export const Card = () => null // mine\n",
    })
    ensure_local_modules(root)
    assert (root / "src/components/ui/card.tsx").read_text() == "export const Card = () => null // mine\n"
    assert "export function cn" in (root / "src/lib/utils.ts").read_text()


def test_case_variant_file_does_not_count_and_is_not_clobbered(tmp_path):
    # The generator writes ui/Card.tsx; pages import ui/card. Linux is case-sensitive, so that import is missing.
    root = _tree(tmp_path, {"src/pages/D.tsx": "import { Card } from '@/components/ui/card'\n",
                            "src/components/ui/Card.tsx": "export const Card = () => null // generated\n"})
    ensure_local_modules(root)
    assert (root / "src/components/ui/Card.tsx").read_text() == "export const Card = () => null // generated\n"


def test_traversal_specifiers_never_write_outside_src(tmp_path):
    root = tmp_path / "fe"
    outside = tmp_path / "outside"
    outside.mkdir()
    _tree(root, {"src/pages/A.tsx": (
        "import { X } from '@/../outside/x'\nimport { Y } from '../../../outside/y'\n"
        "import { Z } from '../../../../../../../../tmp/p05_traversal_probe/z'\n"
        "import { L } from '@/link/l'\nimport { M } from '../link/m'\n")})
    (root / "src" / "link").symlink_to(outside, target_is_directory=True)
    ensure_local_modules(root)
    assert list(outside.iterdir()) == []
    assert not Path("/tmp/p05_traversal_probe").exists()
    assert [p for p in tmp_path.rglob("*.ts*") if not p.is_relative_to(root / "src")] == []
