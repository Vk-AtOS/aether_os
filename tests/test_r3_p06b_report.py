"""KAN-184: the p06b report states what its 'verification' is (a static check), and its gate behaves on both outcomes."""
from types import SimpleNamespace

from aether_os.phases.p06b_formal_verification import task_agent


def _r(status, inv="INV-001", route="GET /x"):
    return SimpleNamespace(invariant_id=inv, invariant_name="n", route_name=route, status=status, proof_method="m",
                           solver_time_ms=1, confidence=1.0, violation_detail="")


def test_report_declares_its_scope_and_verdicts_follow_the_results():
    rep = task_agent._build_report([_r("VERIFIED")], "p", "crm", 3, "4.x", 5, True)
    assert "not a proof of runtime behaviour" in rep["scope"] and rep["overall_verdict"] == "PASS"
    assert task_agent._build_report([_r("VERIFIED"), _r("VIOLATED", route="POST /y")], "p", "crm", 3, "4.x", 5, True)["overall_verdict"] == "FAIL"
    # without z3 nothing was checked: PARTIAL, never PASS
    assert task_agent._build_report([], "p", "crm", 3, "unavailable", 0, False, "z3-solver not installed")["overall_verdict"] == "PARTIAL"
