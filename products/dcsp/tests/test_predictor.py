from __future__ import annotations
import pytest
from datetime import datetime, timedelta
from src.intelligence.predictor import (
    FailurePredictor,
    FailureRecord,
    PredictionResult,
    DECAY_HALF_LIFE_DAYS,
    MIN_OCCURRENCES,
    RECURRENCE_THRESHOLD,
    PREDICTOR
)

@pytest.fixture
def predictor():
    p = FailurePredictor()
    return p

def test_record_failure(predictor):
    predictor.record_failure(
        "AttributeError", "python",
        "fp1", "acme/api")
    assert "AttributeError" in \
        predictor.known_error_types

def test_predict_requires_min_occurrences(
        predictor):
    """Single occurrence → no prediction."""
    predictor.record_failure(
        "TypeError", "python", "fp1")
    result = predictor.predict("TypeError")
    assert result is None

def test_predict_with_enough_data(predictor):
    """Two occurrences → prediction."""
    for _ in range(2):
        predictor.record_failure(
            "AttributeError", "python",
            "fp1", "acme/api")
    result = predictor.predict(
        "AttributeError")
    assert result is not None
    assert result.error_type == \
        "AttributeError"
    assert 0.0 <= result.recurrence_score \
        <= 1.0

def test_more_occurrences_higher_score(
        predictor):
    """More failures → higher score."""
    for _ in range(2):
        predictor.record_failure(
            "ErrorA", "python", "fp1")
    for _ in range(8):
        predictor.record_failure(
            "ErrorB", "python", "fp2")
    r_a = predictor.predict("ErrorA")
    r_b = predictor.predict("ErrorB")
    assert r_b.recurrence_score > \
        r_a.recurrence_score

def test_old_failures_score_lower(predictor):
    """Old failures decay in score."""
    old_time = datetime.utcnow() - \
        timedelta(days=60)
    recent_time = datetime.utcnow() - \
        timedelta(days=1)

    old_p = FailurePredictor()
    for _ in range(3):
        old_p.record_failure(
            "KeyError", "python", "fp1",
            occurred_at=old_time)

    new_p = FailurePredictor()
    for _ in range(3):
        new_p.record_failure(
            "KeyError", "python", "fp1",
            occurred_at=recent_time)

    old_r = old_p.predict("KeyError")
    new_r = new_p.predict("KeyError")
    assert new_r.recurrence_score > \
        old_r.recurrence_score

def test_severity_levels(predictor):
    """High occurrences → critical severity."""
    for _ in range(10):
        predictor.record_failure(
            "RuntimeError", "python",
            "fp1", "r/a")
    result = predictor.predict(
        "RuntimeError")
    assert result.predicted_severity in \
        ["high", "critical"]

def test_predict_all_sorted(predictor):
    for _ in range(2):
        predictor.record_failure(
            "ErrorA", "python", "fp1")
    for _ in range(5):
        predictor.record_failure(
            "ErrorB", "python", "fp2")
    results = predictor.predict_all()
    assert len(results) == 2
    assert results[0].recurrence_score >= \
        results[1].recurrence_score

def test_predict_unknown_type(predictor):
    result = predictor.predict(
        "NonExistentError")
    assert result is None

def test_contributing_repos(predictor):
    predictor.record_failure(
        "ImportError", "python", "fp1",
        repo_name="acme/svc-a")
    predictor.record_failure(
        "ImportError", "python", "fp2",
        repo_name="acme/svc-b")
    result = predictor.predict("ImportError")
    assert "acme/svc-a" in \
        result.contributing_repos
    assert "acme/svc-b" in \
        result.contributing_repos

def test_is_likely_to_recur_flag(predictor):
    """High score sets is_likely_to_recur."""
    for _ in range(5):
        predictor.record_failure(
            "ValueError", "python", "fp1",
            occurred_at=datetime.utcnow())
    result = predictor.predict("ValueError")
    assert result.is_likely_to_recur is True

def test_score_log_snippet_match(predictor):
    for _ in range(3):
        predictor.record_failure(
            "AttributeError", "python",
            "fp1")
    result = predictor.score_log_snippet(
        "AttributeError: NoneType object")
    assert result["score"] > 0.0
    assert result["severity"] != "unknown"

def test_score_log_snippet_no_match(
        predictor):
    result = predictor.score_log_snippet(
        "Some unknown log content here")
    assert result["severity"] == "unknown"
    assert result["score"] == 0.0

def test_predictor_clear(predictor):
    predictor.record_failure(
        "TypeError", "python", "fp1")
    predictor.record_failure(
        "TypeError", "python", "fp2")
    predictor.clear()
    assert predictor.known_error_types == []

def test_prediction_api_endpoint():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "pred_api_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/intelligence/predictions",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "predictions" in data
    assert "total" in data
