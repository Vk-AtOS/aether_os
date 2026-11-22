"""KAN-209: p05 writes the whole fixed UI primitive set up front, so missing_modules has nothing to add for it."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aether_os.phases.p05_frontend.helpers import write_ui_components
from aether_os.phases.p05_frontend.missing_modules import ensure_local_modules
from aether_os.phases.p05_frontend.ui_primitives import UI_PRIMITIVES, write_fixed_primitive_set

NAMES = ("Button", "Card", "Input", "Table", "Select", "Badge", "Dialog", "Label", "Textarea", "Separator", "Tabs")


def _pages(src):
    (src / "pages").mkdir(parents=True)
    imports = "\n".join(f"import {{ {n} }} from '@/components/ui/{n}'" for n in NAMES)
    (src / "pages" / "Home.tsx").write_text(imports + "\nimport { cn } from '@/lib/utils'\nexport default () => null\n")


def test_every_primitive_is_on_disk_after_write_ui_components(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEGEN_TEMPLATES_FIRST", raising=False)
    src = tmp_path / "frontend" / "src"
    write_ui_components(src)
    for n in NAMES:
        assert (src / "components" / "ui" / f"{n}.tsx").is_file(), n
    assert (src / "lib" / "utils.ts").is_file()
    assert {main for _, main in UI_PRIMITIVES.values()} <= {p.stem for p in (src / "components" / "ui").glob("*.tsx")}


def test_missing_modules_has_nothing_to_add_for_the_fixed_set(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEGEN_TEMPLATES_FIRST", raising=False)
    fe = tmp_path / "frontend"
    write_ui_components(fe / "src")
    _pages(fe / "src")
    assert ensure_local_modules(fe) == []


def test_flag_off_leaves_the_old_ten(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEGEN_TEMPLATES_FIRST", "0")
    write_ui_components(tmp_path / "src")
    assert not (tmp_path / "src" / "components" / "ui" / "Dialog.tsx").exists()


def test_existing_files_are_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEGEN_TEMPLATES_FIRST", raising=False)
    ui = tmp_path / "src" / "components" / "ui"
    ui.mkdir(parents=True)
    (ui / "Dialog.tsx").write_text("// mine\n")
    write_ui_components(tmp_path / "src")
    assert (ui / "Dialog.tsx").read_text() == "// mine\n"


def test_primitives_typecheck(tmp_path):
    """tsc --noEmit over the written set. Needs a node_modules with typescript and @types/react: set
    AETHER_TS_NODE_MODULES to one (CI has the dashboard's); skipped when none is available."""
    nm = os.environ.get("AETHER_TS_NODE_MODULES", "")
    if not nm or not (Path(nm) / ".bin" / "tsc").exists():
        pytest.skip("AETHER_TS_NODE_MODULES not set")
    write_fixed_primitive_set(tmp_path / "src")  # the dependency-free set; the radix-based ten need npm install
    (tmp_path / "node_modules").symlink_to(nm)
    p = subprocess.run([str(Path(nm) / ".bin" / "tsc"), "--noEmit", "--jsx", "react-jsx", "--skipLibCheck", "--strict",
                        "--moduleResolution", "bundler", "--module", "esnext", "--target", "es2020",
                        *map(str, (tmp_path / "src").rglob("*.ts*"))],
                       capture_output=True, text=True, timeout=240, cwd=str(tmp_path))
    assert p.returncode == 0, p.stdout[-1500:]
