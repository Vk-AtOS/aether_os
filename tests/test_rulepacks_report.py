"""KAN-243 rule packs: scan_project / Report / repair_prompt, plus a score of the real generated-output fixtures."""
import json
from pathlib import Path

from aether_os.core.rulepacks import repair_prompt, scan_project
from aether_os.core.rulepacks.base import Finding, Project
from aether_os.tests import rulepacks_fixtures as F

FIXTURES = Path(__file__).parent / "fixtures"
TASKS = "backend/app/routers/tasks.py"


def test_clean_project_is_not_blocking(tmp_path):
    r = scan_project(F.write_project(tmp_path))
    assert r.findings == [] and not r.blocking and set(r.counts.values()) == {0}
    assert set(r.by_pack) == {"design", "security", "prodready"}


def test_defective_project_is_blocking_and_serialises(tmp_path):
    bad = {TASKS: F.TASKS_ROUTER.replace("router = APIRouter(dependencies=[Depends(get_current_user)])", "router = APIRouter()")
           .replace(", user: User = Depends(get_current_user)", "").replace(" Task.owner_id == user.id", " True")
           + '\n\ndef raw(db, q):\n    return db.execute(f"SELECT * FROM tasks WHERE title = \'{q}\'")\n',
           "frontend/src/components/Logo.tsx": 'export const Logo = () => <img src="/logo.svg" />;\n'}
    r = scan_project(F.write_project(tmp_path, bad))
    assert r.blocking and r.counts["high"] >= 2
    data = json.loads(r.to_json())
    assert data["blocking"] is True
    assert {f["rule_id"] for f in data["findings"]["security"]} >= {"SEC-004", "SEC-007"}
    assert [f["rule_id"] for f in data["findings"]["design"]] == ["DES-005"]
    assert data["counts_by_pack"]["design"]["medium"] == 1
    assert r.files()[0] == TASKS  # most severe file first


def test_public_routes_from_the_generator_are_honoured(tmp_path):
    no_auth = {TASKS: F.TASKS_ROUTER.replace("router = APIRouter(dependencies=[Depends(get_current_user)])", "router = APIRouter()")
               .replace(", user: User = Depends(get_current_user)", "").replace(" Task.owner_id == user.id", " True")}
    r = scan_project(F.write_project(tmp_path, no_auth), public_routes=["GET /tasks/*", "GET /tasks", "/auth/login"])
    assert not [f for f in r.findings if f.rule_id == "SEC-007"]


def test_repair_prompt_renders_one_file_most_severe_first():
    fs = [Finding("DES-005", "design", "medium", "a.tsx", 9, "<img> without alt", "add alt", "<img src=x />"),
          Finding("SEC-015", "security", "high", "a.tsx", 20, "dangerouslySetInnerHTML without sanitizing", "use DOMPurify"),
          Finding("SEC-004", "security", "high", "b.py", 3, "SQL built", "bind params")]
    text = repair_prompt(fs, "a.tsx")
    lines = text.splitlines()
    assert "2 problem(s) in `a.tsx`" in lines[0] and "complete corrected file" in lines[0]
    assert lines[1].startswith("1. [high] SEC-015 line 20:") and lines[2].startswith("2. [medium] DES-005 line 9: `<img src=x />`")
    assert "b.py" not in text and repair_prompt(fs, "c.py") == ""
    many = [Finding("DES-004", "design", "low", "a.tsx", i, "off grid", "fix") for i in range(1, 30)]
    assert "omitted" in repair_prompt(many, "a.tsx", max_items=5)


def test_scan_real_generated_fixtures():
    """The pipeline's own captured output (runs 20/21) scores with findings, and nothing crashes on partial trees."""
    total = {}
    for name in ("run20", "run21", "quality_golden"):
        r = scan_project(FIXTURES / name)
        total[name] = r.counts
        assert all(f.file and f.rule_id for f in r.findings if f.pack != "prodready")
    assert total["run20"]["medium"] >= 4  # icon-only buttons, missing states, unlabeled input


def test_secret_findings_store_a_redacted_snippet_only(tmp_path):
    secret_value = F.FAKE_HEX
    over = {"backend/app/extra.py": f'STRIPE_API_KEY = "{secret_value}"\nKEY = "{F.FAKE_STRIPE_LIVE}"\n',
            ".env": f"SECRET_KEY={secret_value}\n",
            ".env.example": F.ENV_EXAMPLE + f"WEBHOOK_SECRET={F.FAKE_WEBHOOK}\n",
            "backend/certs/server.key": F.FAKE_PRIVATE_KEY}
    r = scan_project(F.write_project(tmp_path, over))
    secret = [f for f in r.findings if f.rule_id in ("SEC-001", "SEC-003", "SEC-021", "PRD-006")]
    assert {f.rule_id for f in secret} == {"SEC-001", "SEC-003", "SEC-021", "PRD-006"}
    assert all(f.snippet.endswith("***") for f in secret if f.snippet)
    dumped = r.to_json() + "".join(repair_prompt(r.findings, f) for f in r.files())
    for raw in (secret_value, F.FAKE_STRIPE_LIVE, F.FAKE_WEBHOOK, "MIIBOgIBAAJBAK"):
        assert raw not in dumped
    assert 'STRIPE_API_KEY = "a8f9***' in dumped  # key name + first 4 chars stays useful for the repair


def test_symlinks_and_oversized_files_are_never_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text(f'TOKEN_SECRET = "{F.FAKE_AWS}"\n')
    proj = F.write_project(tmp_path / "proj")
    (proj / "backend/app/linked.py").symlink_to(outside / "leak.py")
    (proj / "backend/linkdir").symlink_to(outside, target_is_directory=True)
    (proj / "backend/app/huge.py").write_text("x = 1\n" * 200_000)  # > 512 KiB
    p = Project.load(proj)
    assert not [f for f in p.files if "linked" in f or "linkdir" in f or "huge" in f]
    assert p.text("backend/app/linked.py") == "" and p.text("../outside/leak.py") == ""
    assert scan_project(proj).findings == []
