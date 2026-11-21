"""p05 missing_modules must never rewrite or delete a file outside src through a planted symlink."""
from __future__ import annotations

import pytest

from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules

CASE_IMPORT = "import { Card } from '../components/ui/card'\n"


def test_symlinked_importer_outside_src_is_not_rewritten(tmp_path):
    outside = tmp_path / "outside.tsx"
    outside.write_text(CASE_IMPORT)
    root = tmp_path / "fe"
    (root / "src/pages").mkdir(parents=True)
    (root / "src/components/ui").mkdir(parents=True)
    (root / "src/components/ui/Card.tsx").write_text("export const Card = () => null\n")
    (root / "src/pages/Link.tsx").symlink_to(outside)
    ensure_local_modules(root)
    assert outside.read_text() == CASE_IMPORT
    assert (root / "src/pages/Link.tsx").is_symlink()


def test_symlinked_dir_importer_is_not_rewritten(tmp_path):
    outdir = tmp_path / "outdir"
    outdir.mkdir()
    (outdir / "X.tsx").write_text(CASE_IMPORT)
    root = tmp_path / "fe"
    (root / "src/components/ui").mkdir(parents=True)
    (root / "src/components/ui/Card.tsx").write_text("export const Card = () => null\n")
    (root / "src/pages").symlink_to(outdir, target_is_directory=True)
    ensure_local_modules(root)
    assert (outdir / "X.tsx").read_text() == CASE_IMPORT


def test_symlinked_generated_duplicate_is_not_deleted(tmp_path):
    outside = tmp_path / "victim.tsx"
    outside.write_text("// aether:generated-module\nexport const Card = () => null\n")
    root = tmp_path / "fe"
    (root / "src/components/ui").mkdir(parents=True)
    (root / "src/components/ui/Card.tsx").write_text("export const Card = () => null\n")
    try:
        (root / "src/components/ui/card.tsx").symlink_to(outside)
    except FileExistsError:
        pytest.skip("case-insensitive filesystem: Card.tsx and card.tsx cannot coexist")
    ensure_local_modules(root)
    assert outside.exists()
