"""KAN-223: generated pages read the backend's {items,...} list shape (run 20 fixture: ProjectPage/TaskPage read `.data`)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aether_os.phases.p05_frontend.api_contract import enforce_list_contract, unwrap_raw_query_calls
from aether_os.phases.p05_frontend.code_writer_parts.part02 import _generate_api

FIX = Path(__file__).parent / "fixtures" / "run20"


def _backend_fields() -> list[str]:
    body = (FIX / "schemas_head.py").read_text().split("class PaginatedResponse(BaseModel):")[1].split("class ")[0]
    return re.findall(r"^\s+(\w+):", body, re.M)


@pytest.mark.parametrize("page", ["ProjectPage.tsx", "TaskPage.tsx"])
def test_run20_pages_are_rewritten_to_items(page):
    src = (FIX / page).read_text()
    assert re.search(r"\bdata\??\.data\b|\bdata: \w+\[\]", src)  # the run-20 bug is present in the fixture
    out = enforce_list_contract(src, page)
    assert out is not None
    assert not re.search(r"\.data\??\.(map|length)\b|\.data\.data\b", out)
    assert re.search(r"\bitems\??: \w+\[\]", out)
    assert re.search(r"\.items\b", out)
    assert "data: Project[]" not in out and "data: Task[]" not in out


def test_unrelated_axios_data_is_untouched():
    code = "const r = await apiClient.get('/x'); return r.data.map(a => a)\nexport default function P() { return null }"
    assert enforce_list_contract(code) == code


def test_unfixable_page_returns_none_for_template_fallback():
    assert enforce_list_contract("type PageListResponse = { data: Foo }\nexport default 1") is None
    assert enforce_list_contract("const x = res.data.data\nexport default 1") == "const x = res.data.items\nexport default 1"


def test_generated_api_list_type_matches_backend_paginated_response():
    ents = [{"table": t, "columns": ["id"]} for t in ("projects", "tasks", "users")]
    out = _generate_api(ents, {})
    iface = re.search(r"interface Paginated<T> \{([^}]*)\}", out).group(1)
    assert re.findall(r"(\w+):", iface) == _backend_fields() == ["items", "total", "page", "page_size", "limit"]
    for e in ("projects", "tasks", "users"):
        block = out.split(f"export const {e}Api = {{")[1].split("\n}")[0]
        assert "Paginated<" in block and "get: (id" in block
        for fn in ("list:", "create:", "update:", "remove:"):
            assert fn in block


# Production run 21 (22 Nov 2026): ProjectPage fetched users with a raw apiClient.get as its queryFn and read
# data.items from the axios response; TaskPage read tasksData?.items.length while the body was undefined.


def test_raw_apiclient_query_returns_the_body():
    src = "useQuery({ queryKey: ['u'], queryFn: () => apiClient.get('/users', { params: { page: 1, page_size: 200 } }), select: (d) => d.items })"
    out = unwrap_raw_query_calls(src)
    assert "apiClient.get('/users', { params: { page: 1, page_size: 200 } }).then(r => r.data)" in out


def test_raw_call_that_already_unwraps_is_left_alone():
    src = "queryFn: () => apiClient.get('/x').then(r => r.data),"
    assert unwrap_raw_query_calls(src) == src


def test_parentheses_inside_strings_do_not_confuse_the_scanner():
    src = "queryFn: () => apiClient.get(`/x?q=${encodeURIComponent(q)}`, { params: { s: ')' } }),"
    out = unwrap_raw_query_calls(src)
    assert out.endswith("{ params: { s: ')' } }).then(r => r.data),")


def test_items_reads_are_null_safe_after_the_contract_fix():
    out = enforce_list_contract("{tasksData?.items.length === 0 && <p/>}{tasksData?.items.map(t => t.id)}", "TaskPage")
    assert "?.items?.length" in out and "?.items?.map" in out
