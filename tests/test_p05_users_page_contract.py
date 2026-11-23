"""Production run 33 (23 Nov 2026): the model-written Users page had a Create button bound to form="user-form" while the
form had no such id (clicking did nothing) and mapped password -> password_hash. The users API is a fixed template
(KAN-224), so its page is the fixed template; other model-written pages with these defects are refused."""
import inspect

from aether_os.phases.p05_frontend import domain_assembler
from aether_os.phases.p05_frontend.llm_page_writer import page_defects

RUN33 = """
<form onSubmit={handleSubmit} className="space-y-4"><Input id="email" type="email" /></form>
<Button type="submit" form="user-form">Create</Button>
const payload = password ? { ...rest, password_hash: password } : rest;
"""


def test_run_33_page_defects_are_found():
    found = page_defects(RUN33)
    assert any('form "user-form"' in d for d in found)
    assert any("password_hash" in d for d in found)


def test_a_button_bound_to_an_existing_form_is_fine():
    ok = '<form id="task-form" onSubmit={s}></form><Button type="submit" form="task-form">Save</Button>'
    assert page_defects(ok) == []


def test_the_users_page_is_always_the_template():
    src = inspect.getsource(domain_assembler)
    ir_branch = src.index("if is_user_entity(ir_entity):")
    assert ir_branch < src.index("_llm_code = await write_entity_page_llm(", ir_branch - 2000)
    assert 'if ent.get("table") == "users" or ent.get("name") == "User":' in src
