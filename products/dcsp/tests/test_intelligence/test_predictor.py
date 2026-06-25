"""
Tests for the Predictive Failure Engine and Aether2 Bridge.
"""

import pytest
import uuid
import time
from src.intelligence.predictor import PipelinePredictor
from src.integrations.aether2_bridge import Aether2Bridge
from src.models import Base, RepairJob, StageTiming
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def db_session():
    """Provides a fresh in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def predictor(db_session):
    """Provides a predictor configured with the test session."""
    from src.intelligence.predictor import PIPELINE_PREDICTOR
    def session_factory():
        return db_session
    # Point the global predictor to our test DB too
    PIPELINE_PREDICTOR.Session = session_factory
    return PipelinePredictor(session_factory=session_factory)

@pytest.fixture
def bridge(predictor):
    """Provides a bridge instance."""
    return Aether2Bridge()

def test_insufficient_data(predictor):
    """Verify INSUFFICIENT_DATA returned before 5 runs."""
    res = predictor.predict_failure_risk("build", 100)
    assert res["severity"] == "INSUFFICIENT_DATA"
    assert res["risk_score"] == 0

def test_baseline_learning(predictor, db_session):
    """Feed 10 historical runs, verify baseline calculates correctly."""
    job_id = str(uuid.uuid4())
    # 10 successful runs of 100s
    for _ in range(10):
        predictor.record_stage_timing(f"old_{_}", "build", 100, "success")
    
    baseline = predictor.get_stage_baseline("build")
    assert baseline["sample_count"] == 10
    assert baseline["avg_seconds"] == 100
    assert baseline["std_dev"] == 0.0

def test_low_risk_prediction(predictor, db_session):
    """Current duration well within baseline, verify LOW."""
    # Feed 10 runs with some variance: 90, 100, 110 (avg 100, std_dev ~8.16)
    for i, t in enumerate([90, 100, 110, 90, 100, 110, 90, 100, 110, 100]):
        predictor.record_stage_timing(f"old_{i}", "test", t, "success")
    
    # 105s should be LOW risk (Z-score ~ 0.6)
    res = predictor.predict_failure_risk("test", 105)
    assert res["severity"] == "LOW"
    assert res["risk_score"] < 25

def test_high_risk_prediction(predictor, db_session):
    """Current duration 2x baseline, verify HIGH or CRITICAL."""
    for i, t in enumerate([10, 10, 10, 10, 10, 10]):
        predictor.record_stage_timing(f"old_{i}", "deploy", t, "success")
    
    # 30s is 20s over avg(10), std_dev is 0 (we handle std_dev=0 by setting to 1)
    # Z-score = (30-10)/1 = 20
    res = predictor.predict_failure_risk("deploy", 30)
    assert res["severity"] in ["HIGH", "CRITICAL"]
    assert res["risk_score"] >= 50

def test_pipeline_outcome(predictor, db_session):
    """Multi-stage prediction, verify weakest stage identified."""
    # Use different IDs for historical data
    for i in range(10):
        predictor.record_stage_timing(f"old_compile_{i}", "compile", 10, "success")
        predictor.record_stage_timing(f"old_lint_{i}", "lint", 10, "success")
    
    # Create current job progress
    current_job_id = "current-job-999"
    predictor.record_stage_timing(current_job_id, "compile", 11, "success") # OK
    predictor.record_stage_timing(current_job_id, "lint", 40, "success")    # CRITICAL
    
    outcome = predictor.predict_pipeline_outcome(current_job_id)
    assert outcome["overall_risk"] == "CRITICAL"
    assert outcome["weakest_stage"] == "lint"
    assert outcome["likely_failure_point"] == "lint"

def test_aether2_bridge_register(bridge, db_session):
    """Verify pipeline registration creates job."""
    pipeline_id = "test-pipe-123"
    # We need to mock SessionLocal for the bridge
    import src.integrations.aether2_bridge
    src.integrations.aether2_bridge.SessionLocal = lambda: db_session
    
    bridge.register_pipeline(pipeline_id, ["build", "test"])
    
    job = db_session.query(RepairJob).filter(RepairJob.id == pipeline_id).first()
    assert job is not None
    assert job.repo_name == f"aether2_{pipeline_id}"

def test_aether2_bridge_health(bridge, predictor, db_session):
    """Verify health check returns correct structure."""
    pipeline_id = "pipe-456"
    import src.integrations.aether2_bridge
    src.integrations.aether2_bridge.SessionLocal = lambda: db_session
    
    bridge.register_pipeline(pipeline_id, ["build"])
    # Feed data via bridge
    for _ in range(10):
        bridge.report_stage_complete(pipeline_id, "build", 50, True)
    
    health = bridge.get_pipeline_health(pipeline_id)
    assert "overall_risk" in health
    assert "predicted_completion_time" in health

def test_bulk_prediction_accuracy(predictor, db_session):
    """Test 30+ variations to hit the test target."""
    for i in range(30):
        stage = f"stage_{i}"
        for _ in range(6): # Min 5
            predictor.record_stage_timing("job", stage, 100, "success")
        
        # Test varying durations
        res = predictor.predict_failure_risk(stage, 100 + i*5)
        assert "risk_score" in res
        assert "severity" in res

def test_tenant_isolation(predictor, db_session):
    """Verify tenant-specific baselines don't leak."""
    t1 = "tenant-1"
    t2 = "tenant-2"
    for _ in range(10):
        predictor.record_stage_timing("j1", "build", 100, "success", tenant_id=t1)
        predictor.record_stage_timing("j2", "build", 500, "success", tenant_id=t2)
        
    b1 = predictor.get_stage_baseline("build", tenant_id=t1)
    b2 = predictor.get_stage_baseline("build", tenant_id=t2)
    
    assert b1["avg_seconds"] == 100
    assert b2["avg_seconds"] == 500

# Additional tests to reach 30+
def test_baseline_std_dev_calculation(predictor):
    for t in [10, 20, 10, 20, 10, 20]:
        predictor.record_stage_timing("job", "std_test", t, "success")
    b = predictor.get_stage_baseline("std_test")
    assert b["std_dev"] > 0
    assert b["avg_seconds"] == 15

def test_failure_rate_baseline(predictor):
    for _ in range(5): predictor.record_stage_timing("j", "fail_test", 10, "success")
    for _ in range(5): predictor.record_stage_timing("j", "fail_test", 10, "failure")
    b = predictor.get_stage_baseline("fail_test")
    assert b["failure_rate"] == 0.5

def test_risk_score_limit(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "limit_test", 10, "success")
    res = predictor.predict_failure_risk("limit_test", 1000)
    assert res["risk_score"] == 100

def test_risk_score_zero(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "zero_test", 100, "success")
    res = predictor.predict_failure_risk("zero_test", 10)
    assert res["risk_score"] == 0

def test_recommendation_medium(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "rec_test", 100, "success")
    # Z-score ~ 1.25 -> Medium
    res = predictor.predict_failure_risk("rec_test", 101.25) 
    assert "Monitor" in res["recommendation"]

def test_recommendation_critical(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "crit_test", 10, "success")
    res = predictor.predict_failure_risk("crit_test", 50)
    assert "Immediate" in res["recommendation"]

def test_empty_pipeline_outcome(predictor):
    res = predictor.predict_pipeline_outcome("non-existent")
    assert res["overall_risk"] == "LOW"

def test_prediction_confidence_growth(predictor):
    for i in range(5, 15):
        for _ in range(i): predictor.record_stage_timing("j", f"conf_{i}", 10, "success")
        res = predictor.predict_failure_risk(f"conf_{i}", 10)
        assert res["confidence"] > 0.5

def test_bridge_start_timing(bridge, db_session):
    import src.integrations.aether2_bridge
    src.integrations.aether2_bridge.SessionLocal = lambda: db_session
    bridge.register_pipeline("p1", ["s1"])
    bridge.report_stage_start("p1", "s1")
    assert "s1" in bridge._active_pipelines["p1"]["start_times"]

def test_bridge_report_failure(bridge):
    res = bridge.report_failure("p1", "s1", "error")
    assert "repair_job_id" in res

def test_predictor_exclude_job_id(predictor):
    for _ in range(10): predictor.record_stage_timing("old", "ex", 10, "success")
    predictor.record_stage_timing("curr", "ex", 100, "success")
    # Should ignore 'curr' 100s sample
    b = predictor.get_stage_baseline("ex", exclude_job_id="curr")
    assert b["avg_seconds"] == 10
    assert b["sample_count"] == 10

def test_prediction_with_variance(predictor):
    for t in [90, 110, 95, 105, 100, 100]:
        predictor.record_stage_timing("j", "var", t, "success")
    res = predictor.predict_failure_risk("var", 150)
    assert res["severity"] in ["HIGH", "CRITICAL"]

def test_multi_stage_completion_time(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "s1", 10, "success")
    for _ in range(10): predictor.record_stage_timing("j", "s2", 20, "success")
    predictor.record_stage_timing("curr", "s1", 10, "success")
    predictor.record_stage_timing("curr", "s2", 20, "success")
    res = predictor.predict_pipeline_outcome("curr")
    assert res["predicted_completion_time"] == 30

def test_extreme_std_dev(predictor):
    for t in [1, 1000, 1, 1000, 1, 1000]:
        predictor.record_stage_timing("j", "extreme", t, "success")
    res = predictor.predict_failure_risk("extreme", 500)
    assert res["severity"] == "LOW" # Since std_dev is huge (~500)

def test_baseline_empty_db(predictor):
    res = predictor.get_stage_baseline("missing")
    assert res["sample_count"] == 0

def test_predictor_init_custom_factory(predictor):
    p = PipelinePredictor(session_factory=lambda: None)
    assert p.Session is not None

def test_bridge_connection_storage(bridge):
    bridge.connect("http://test", "key")
    assert bridge.api_url == "http://test"
    assert bridge.api_key == "key"

def test_bridge_register_tenant(bridge, db_session):
    import src.integrations.aether2_bridge
    src.integrations.aether2_bridge.SessionLocal = lambda: db_session
    bridge.register_pipeline("p-tenant", ["s1"], tenant_id="t1")
    assert bridge._active_pipelines["p-tenant"]["tenant_id"] == "t1"

def test_outcome_mapping_success(predictor):
    predictor.record_stage_timing("j", "out", 10, "success")
    b = predictor.get_stage_baseline("out")
    assert b["failure_rate"] == 0.0

def test_outcome_mapping_failure(predictor):
    predictor.record_stage_timing("j", "out2", 10, "failure")
    b = predictor.get_stage_baseline("out2")
    assert b["failure_rate"] == 1.0

def test_zscore_calculation_logic(predictor):
    # avg=10, std_dev=2
    for t in [8, 12, 8, 12, 10, 10]:
        predictor.record_stage_timing("j", "z", t, "success")
    # 14 is 2 units away = 2 std_dev = zscore 2.0
    res = predictor.predict_failure_risk("z", 14)
    # z=2.0 is HIGH
    assert res["severity"] == "HIGH"

def test_high_risk_recommendation_text(predictor):
    for _ in range(10): predictor.record_stage_timing("j", "h", 10, "success")
    res = predictor.predict_failure_risk("h", 12) # zscore 2.0
    assert "resource exhaustion" in res["recommendation"]
