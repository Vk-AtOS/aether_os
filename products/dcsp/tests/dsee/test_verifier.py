"""Tests for src.dsee.verifier."""

import pytest
from src.dsee.verifier import verify_stability, VerificationResult
from src.dsee.test_runner import TieredTestRunResult
from src.dsee.impact import ImpactResult


def test_verify_stability_all_pass():
    test_res = TieredTestRunResult(tier=1, passed=True, output="Tests passed.")
    impact_res = ImpactResult(safe=True, risk_level="safe", dependency_ripple_count=3)
    
    res = verify_stability(test_res, impact_res)
    assert res.approved is True
    assert len(res.failures) == 0


def test_verify_stability_tests_failed():
    test_res = TieredTestRunResult(tier=1, passed=False, output="AssertionError in test_foo")
    impact_res = ImpactResult(safe=True, risk_level="safe", dependency_ripple_count=0)
    
    res = verify_stability(test_res, impact_res)
    assert res.approved is False
    assert any("Test suite failed" in f for f in res.failures)


def test_verify_stability_impact_risky():
    test_res = TieredTestRunResult(tier=1, passed=True, output="Tests passed.")
    impact_res = ImpactResult(
        safe=False, 
        risk_level="risky", 
        reasons=["Public function removed"],
        dependency_ripple_count=0
    )
    
    res = verify_stability(test_res, impact_res)
    assert res.approved is False
    assert any("Risk level too high" in f for f in res.failures)
    assert "Public function removed" in res.failures[0]


def test_verify_stability_warnings_introduced():
    # Test DeprecationWarning
    test_res_dep = TieredTestRunResult(tier=1, passed=True, output="DeprecationWarning: old_func is deprecated.")
    impact_res = ImpactResult(safe=True, risk_level="safe", dependency_ripple_count=0)
    
    res = verify_stability(test_res_dep, impact_res)
    assert res.approved is False
    assert any("Warnings introduced: DeprecationWarning" in f for f in res.failures)

    # Test PytestWarning
    test_res_py = TieredTestRunResult(tier=1, passed=True, output="PytestWarning: something went wrong.")
    res = verify_stability(test_res_py, impact_res)
    assert res.approved is False
    assert any("Warnings introduced: PytestWarning" in f for f in res.failures)


def test_verify_stability_ripple_limit_exceeded():
    test_res = TieredTestRunResult(tier=1, passed=True, output="Tests passed.")
    impact_res = ImpactResult(safe=True, risk_level="safe", dependency_ripple_count=10)
    
    res = verify_stability(test_res, impact_res)
    assert res.approved is False
    assert any("Performance threshold exceeded" in f for f in res.failures)
    assert "10 downstream functions affected" in res.failures[0]


def test_verify_stability_multiple_failures():
    test_res = TieredTestRunResult(tier=1, passed=False, output="AssertionError and DeprecationWarning")
    impact_res = ImpactResult(safe=False, risk_level="risky", reasons=["Broken"], dependency_ripple_count=15)
    
    res = verify_stability(test_res, impact_res)
    assert res.approved is False
    assert len(res.failures) == 4
    assert any("Test suite failed" in f for f in res.failures)
    assert any("Risk level too high" in f for f in res.failures)
    assert any("Warnings introduced" in f for f in res.failures)
    assert any("Performance threshold exceeded" in f for f in res.failures)
