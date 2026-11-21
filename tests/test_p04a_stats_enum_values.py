"""Generated stats router compiles whatever text the model puts in a status enum (production Stage 3, 22 Nov 2026:
`_stage_to do_r = ...` from the value "To do" was a SyntaxError)."""
import ast

from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from aether_os.phases.p04a_backend_codegen.ir_generator_helpers import generate_stats_router


def _ir(values):
    ir = DomainIR(domain="general", app_name="Tasks")
    ir.entities = [IREntity(name="Task", table="tasks", fields=[
        IRField(name="title", type="string"),
        IRField(name="status", type="string", enum_values=values),
    ])]
    return ir


def test_free_text_enum_values_compile_and_keep_their_exact_value():
    values = ["To do", "In-Progress", "Won't fix", "1st review", "done", "To do!"]
    code = generate_stats_router(_ir(values))
    ast.parse(code)                                     # was: SyntaxError
    assert "== 'To do'" in code and '== "Won\'t fix"' in code   # the real value is compared, quoted safely
    assert "_stage_0_to_do_r" in code and "_stage_5_to_do_r" in code    # same slug, still distinct variables
    assert "stats['stage_1st_review']" in code


def test_multi_tenant_variant_also_compiles():
    ast.parse(generate_stats_router(_ir(["Open", "Closed / archived"]), multi_tenancy=True))
