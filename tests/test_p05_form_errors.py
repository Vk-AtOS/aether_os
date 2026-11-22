"""KAN-242: a rejected save must tell the user why. Run 23's create returned 422 and the dialog stayed open, silent."""
from aether_os.core.domain_ir import IREntity, IRField
from aether_os.phases.p05_frontend.code_writer_parts.part02 import _generate_api
from aether_os.phases.p05_frontend.code_writer_parts.part09 import _generate_entity_page
from aether_os.phases.p05_frontend.ir_generators import generate_ir_entity_page
from aether_os.phases.p05_frontend.llm_page_writer import mutations_without_error_handler

ENT = {"table": "projects", "name": "Project", "columns": ["name"], "fields": [{"name": "name", "type": "string"}]}

# The shape of run 23's model-written ProjectPage.tsx: three mutations, onSuccess only.
RUN23_PAGE = """
  const createMutation = useMutation({
    mutationFn: (data: ProjectCreate) => projectsApi.create(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey }); closeModal(); },
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ProjectCreate> }) => projectsApi.update(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey }); closeModal(); },
  });
  const deleteMutation = useMutation<void, Error, number>({
    mutationFn: (id) => projectsApi.remove(id).then(() => undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });
"""


def test_the_api_client_exports_a_message_for_fastapi_errors():
    api = _generate_api([ENT], {"projects": "/projects"})
    assert "export function apiErrorMessage(err: unknown, fallback: string): string" in api
    assert "filter(p => p !== 'body')" in api       # a 422 list names the field: "created_at: Field required"


def test_an_llm_page_with_silent_mutations_is_refused():
    assert mutations_without_error_handler(RUN23_PAGE) == 3
    fixed = RUN23_PAGE.replace("onSuccess:", "onError: (e) => setError(apiErrorMessage(e, 'x')),\n    onSuccess:")
    assert mutations_without_error_handler(fixed) == 0


def test_template_page_toasts_the_server_reason():
    page = _generate_entity_page(ENT, {"projects": "/projects"})
    assert page.count("apiErrorMessage(err,") == 3
    assert "apiErrorMessage }} from '../lib/api'" not in page and "apiErrorMessage } from '../lib/api'" in page
    assert mutations_without_error_handler(page) == 0


def test_ir_page_shows_the_reason_inside_the_open_dialog():
    page = generate_ir_entity_page(IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")]))
    assert "import { api, apiErrorMessage } from '../lib/api';" in page
    assert "onError: (err: unknown) => setSaveError(apiErrorMessage(err, 'Could not save Project'))" in page
    assert '<p role="alert"' in page and "{saveError}" in page
    assert mutations_without_error_handler(page) == 0
