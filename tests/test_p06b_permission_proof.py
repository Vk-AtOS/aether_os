"""KAN-100: p06b proves the permission RULE the generated app enforces (INV-008/009), not an AST boolean."""
import asyncio
from types import SimpleNamespace

import pytest

from aether_os.phases.p04a_backend_codegen.helpers_permissions import _generate_permissions_service
from aether_os.phases.p06b_formal_verification import z3_permissions as zp
from aether_os.phases.p06b_formal_verification.task_agent import run


def _generated(tmp_path, permissions, roles=("Admin", "Viewer")):
    _generate_permissions_service(tmp_path, {"roles": list(roles), "permissions": permissions})
    return (tmp_path / "services" / "permissions.py").read_text()


GOOD = {"Admin": {"*": ["*"]}, "Viewer": {"*": ["read"], "invoices": ["read", "list"]}}


def _by_id(results):
    return {r.invariant_id: r for r in results}


def test_a_sound_table_is_proved(tmp_path):
    out = _by_id(zp.check_permission_rule(_generated(tmp_path, GOOD)))
    assert out["INV-008"].status == "VERIFIED" and out["INV-009"].status == "VERIFIED"
    assert "UNSAT" in out["INV-008"].proof_method or "exhaustive" in out["INV-008"].proof_method


def test_a_read_only_role_with_one_delete_grant_is_a_counter_example(tmp_path):
    bad = {"Admin": {"*": ["*"]}, "Viewer": {"*": ["read"], "invoices": ["read", "delete"]}}
    out = _by_id(zp.check_permission_rule(_generated(tmp_path, bad)))
    assert out["INV-009"].status == "VIOLATED"
    assert "invoices" in out["INV-009"].violation_detail and "delete" in out["INV-009"].violation_detail
    assert out["INV-008"].status == "VERIFIED"                 # the unknown-role property is independent


def test_a_wildcard_action_for_a_read_only_role_is_caught(tmp_path):
    bad = {"Admin": {"*": ["*"]}, "Viewer": {"*": ["*"]}}
    assert _by_id(zp.check_permission_rule(_generated(tmp_path, bad)))["INV-009"].status == "VIOLATED"


def test_no_read_only_role_means_not_applicable(tmp_path):
    out = _by_id(zp.check_permission_rule(_generated(tmp_path, {"Admin": {"*": ["*"]}}, roles=("Admin",))))
    assert out["INV-009"].status == "N/A" and out["INV-008"].status == "VERIFIED"


def test_a_decision_function_that_is_not_the_modelled_rule_is_unverifiable(tmp_path):
    src = _generated(tmp_path, GOOD).replace(
        '"""Return True if the given role may perform action on resource."""', '"""x"""\n    return True')
    assert src != _generated(tmp_path, GOOD)
    out = zp.check_permission_rule(src)
    assert {r.status for r in out} == {"UNVERIFIABLE"}        # proving another rule would be a false comfort


def test_a_non_literal_table_is_unverifiable():
    out = zp.check_permission_rule("PERMISSIONS = build()\n")
    assert {r.status for r in out} == {"UNVERIFIABLE"}


def test_z3_and_exhaustive_engines_agree(tmp_path):
    pytest.importorskip("z3")
    tables = [GOOD, {"Admin": {"*": ["*"]}, "Viewer": {"*": ["read"], "invoices": ["delete"]}},
              {"Editor": {"posts": ["create"]}, "Viewer": {"*": ["*"]}}]
    for t in tables:
        _, resources, actions = zp._domains(t)
        for roles, acts in (([zp._OTHER], None), ([r for r in t if r == "Viewer"], list(zp._MUTATING) + ["*", zp._OTHER])):
            z = zp._violations_z3(t, roles, acts)
            e = zp._violations_exhaustive(t, roles, acts)
            assert (z is None) == (not e), (t, roles, z, e)


def test_the_report_carries_the_proof_and_a_violation_fails_the_run(tmp_path):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    bad = {"Admin": {"*": ["*"]}, "Viewer": {"*": ["read", "delete"]}}
    _generate_permissions_service(proj / "src", {"roles": ["Admin", "Viewer"], "permissions": bad})
    res = asyncio.run(run(SimpleNamespace(input_data={"project_dir": str(proj)}), [], tmp_path / "out"))
    assert res.metadata["overall_verdict"] == "FAIL"           # z3 or not: a proven violation is a FAIL
    assert any("INV-009" in i for i in res.issues)
