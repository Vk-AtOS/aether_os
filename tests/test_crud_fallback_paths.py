"""Fallback CRUD routes live at /api/<table> without a trailing slash, like the model-written ones (acceptance run 14:
with the SPA catch-all in front, /api/projects never redirected to '/api/projects/')."""
from aether_os.phases.p04a_backend_codegen.crud_generator import _fallback_crud_routers


def test_list_and_create_have_no_trailing_slash():
    code = _fallback_crud_routers([{"name": "Project", "table": "projects"}])
    assert "@projects_router.get('', response_model=dict)" in code
    assert "@projects_router.post('', status_code=status.HTTP_201_CREATED" in code
    assert ".get('/'," not in code and ".post('/'," not in code
