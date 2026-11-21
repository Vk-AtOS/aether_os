"""Golden example seeding builds rows PostgreSQL accepts (KAN-47 regression: 41-char run ids rolled back the whole seed)."""
import json
from pathlib import Path

from aether_os.gateway.api_utils import golden_seed_rows

REAL_DIR = Path(__file__).resolve().parent.parent / "core" / "knowledge_graph" / "golden_examples"


def test_real_examples_fit_the_columns():
    rows = golden_seed_rows(REAL_DIR)
    assert len(rows) >= 100  # the app_description_to_domain_ir examples; entity records are not build examples
    assert all(len(r["run_id"]) == 36 for r in rows)
    assert len({r["run_id"] for r in rows}) == len(rows)  # uq_golden_build_run
    assert all(len(r["domain"]) <= 50 and len(r["project_name"]) <= 255 for r in rows)


def test_non_build_examples_are_skipped(tmp_path):
    (tmp_path / "mixed.json").write_text(json.dumps({"domain": "saas", "examples": [
        {"input": "a CRM", "output": {"entities": []}},
        {"type": "bug_to_fix", "input": {"code": "x"}, "output": "fixed"},
        {"input": {"odd": 1}, "output": "str"},
        {"name": "Students", "fields": []},
    ]}))
    (tmp_path / "broken.json").write_text("{not json")
    rows = golden_seed_rows(tmp_path)
    assert [r["domain"] for r in rows] == ["saas"]
    assert golden_seed_rows(tmp_path)[0]["run_id"] == rows[0]["run_id"]  # stable across starts
