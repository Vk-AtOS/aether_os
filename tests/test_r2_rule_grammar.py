"""KAN-169: the business-rule grammar covers the forms models actually write and nothing executable."""
import pytest

from aether_os.phases.p04a_backend_codegen.ir_generators import _pydantic_validators, _sql_check_constraints
from aether_os.phases.p04a_backend_codegen.rule_grammar import parse_rule
from types import SimpleNamespace


def R(expr, name="r1", entity="E"):
    return SimpleNamespace(name=name, expression=expr, entity=entity, error_message="")


@pytest.mark.parametrize("expr,sql", [
    ("salary > 0", "salary > 0"),
    ("age >= 18 AND age <= 65", "age >= 18 AND age <= 65"),
    ("age between 18 and 65", "age >= 18 AND age <= 65"),
    ("status in ('open', 'closed')", "status IN ('open', 'closed')"),
    ("qty in (1,2,3)", "qty IN (1, 2, 3)"),
    ("end_date > start_date", "end_date > start_date"),
    ("email is not null", "email IS NOT NULL"),
    ("a == 1", "a = 1"),
    ("(price >= 0)", "price >= 0"),
])
def test_accepted_forms(expr, sql):
    assert " AND ".join(t.sql() for t in parse_rule(expr)) == sql


@pytest.mark.parametrize("expr", [
    "amount > 0'); import os; os.system('x'); ('", "salary > 0 or 1=1", "x in (select 1)", "len(name) > 3",
    "a > 1 and b >", "", "x in ('a\\')", "price > 0; drop table users",
])
def test_everything_else_is_rejected(expr):
    assert parse_rule(expr) is None


def test_generators_emit_sql_and_validators_from_parsed_terms():
    rules = [R("age between 18 and 65", "age_ok"), R("status in ('open','closed')", "st"), R("end > start", "dates")]
    sql = _sql_check_constraints("E", rules, {"age", "status", "end", "start"})
    assert len(sql) == 3 and "age >= 18 AND age <= 65" in sql[0] and "IN ('open', 'closed')" in sql[1]
    assert _sql_check_constraints("E", rules, {"age"}) == [sql[0]] or len(_sql_check_constraints("E", rules, {"age"})) == 1
    code = "from pydantic import BaseModel, field_validator\nclass M(BaseModel):\n    age: int\n    status: str\n" \
           + "\n".join(_pydantic_validators("E", rules))
    ns = {}
    exec(compile(code, "m.py", "exec"), ns)
    ns["M"](age=30, status="open")
    for bad in ({"age": 10, "status": "open"}, {"age": 30, "status": "nope"}):
        with pytest.raises(Exception):
            ns["M"](**bad)
