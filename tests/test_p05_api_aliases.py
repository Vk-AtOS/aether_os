"""p05: generated lib/api.ts exports singular aliases models reach for (projectApi for projectsApi)."""
from __future__ import annotations

from aether_os.phases.p05_frontend.code_writer_parts.part02 import _generate_api


def test_generated_api_exports_singular_aliases():
    ents = [{"table": t, "columns": ["id", "name"]} for t in ("projects", "tasks", "users")]
    out = _generate_api(ents, {})
    for n in ("project", "task", "user"):
        assert f"export const {n}Api = {n}sApi" in out
    assert out.count("export const userApi") == 1


def test_alias_never_shadows_a_real_entity_api():
    ents = [{"table": t, "columns": ["id"]} for t in ("task", "tasks")]
    out = _generate_api(ents, {})
    assert out.count("export const taskApi") == 1
