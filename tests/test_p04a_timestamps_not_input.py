"""Production run 23 (22 Nov 2026): the spec listed created_at/updated_at as ordinary string fields, the generated
ProjectCreate required them, and every "New Project" save from the generated UI failed with 422."""
import sys
import types

from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from aether_os.phases.p04a_backend_codegen.ir_generators import generate_schemas_py


def _schemas():
    ir = DomainIR(domain="saas", app_name="Tasks")
    ir.entities = [IREntity(name="Project", table="projects", fields=[
        IRField(name="name", type="string"), IRField(name="description", type="string", nullable=True),
        IRField(name="created_at", type="string"), IRField(name="updated_at", type="string"), IRField(name="id", type="integer")])]
    mod = types.ModuleType("generated_schemas")
    sys.modules[mod.__name__] = mod      # postponed annotations resolve against the module, as in the generated app
    exec(generate_schemas_py(ir), mod.__dict__)    # noqa: S102
    return mod.__dict__


def test_create_needs_only_the_client_fields():
    ns = _schemas()
    created = ns["ProjectCreate"](name="Acceptance check item", description="")
    assert created.name == "Acceptance check item"
    assert not {"id", "created_at", "updated_at"} & set(ns["ProjectCreate"].model_fields)
    assert not {"id", "created_at", "updated_at"} & set(ns["ProjectUpdate"].model_fields)


def test_response_still_carries_the_server_set_columns():
    fields = set(_schemas()["ProjectResponse"].model_fields)
    assert {"id", "created_at", "updated_at", "name"} <= fields
