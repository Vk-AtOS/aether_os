"""p05: model-written pages import npm packages the generated package.json lacks."""
from __future__ import annotations

import json

from aether_os.phases.p05_frontend.code_writer_parts.part01 import generate_package_json
from aether_os.phases.p05_frontend.npm_deps import ensure_npm_deps


def _project(tmp_path, page: str):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "P.tsx").write_text(page)
    (tmp_path / "package.json").write_text(generate_package_json("x"))
    return tmp_path


def test_allowlisted_missing_package_is_added(tmp_path):
    root = _project(tmp_path, "import { format } from 'date-fns'\nimport dayjs from 'dayjs'\nimport { z } from 'zod'\n"
                              "import { useState } from 'react'\nimport x from './local'\nimport y from '@/lib/api'\n")
    assert ensure_npm_deps(root) == ["date-fns", "dayjs"]
    deps = json.loads((root / "package.json").read_text())["dependencies"]
    assert deps["date-fns"].startswith("^") and "dayjs" in deps
    assert ensure_npm_deps(root) == []  # idempotent


def test_unknown_package_is_not_added_and_warns(tmp_path, caplog):
    root = _project(tmp_path, "import evil from 'left-padd'\nimport { x } from '@scope/thing/sub'\n")
    before = (root / "package.json").read_text()
    assert ensure_npm_deps(root) == []
    assert (root / "package.json").read_text() == before
    assert "left-padd" in caplog.text and "@scope/thing" in caplog.text


def test_subpath_imports_resolve_to_package_name(tmp_path):
    root = _project(tmp_path, "import { format } from 'date-fns/format'\n")
    assert ensure_npm_deps(root) == ["date-fns"]
