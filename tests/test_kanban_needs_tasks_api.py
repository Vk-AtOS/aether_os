"""The generated Kanban page imports `tasksApi`; it is written only when lib/api.ts really exports it (else vite build fails)."""
from aether_os.phases.p05_frontend.domain_pages import write_domain_pages


def _src(tmp_path, api_text):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "api.ts").write_text(api_text)
    (tmp_path / "pages").mkdir()
    return tmp_path


def test_no_tasks_entity_means_no_kanban_page(tmp_path):
    src = _src(tmp_path, "export const patientsApi = {}\n")
    write_domain_pages(src, "crm", [])
    assert not (src / "pages" / "TasksKanbanPage.tsx").exists()


def test_tasks_entity_gets_the_kanban_page(tmp_path):
    src = _src(tmp_path, "export const tasksApi = {}\n")
    write_domain_pages(src, "crm", [])
    assert "tasksApi" in (src / "pages" / "TasksKanbanPage.tsx").read_text()
