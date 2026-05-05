import pytest
import time
from core.rate_limiter import RateLimiter

def test_concurrent_runs_limit():
    rl = RateLimiter()
    org_id = "test-org"
    for _ in range(5):
        rl.record_run_start(org_id)
    assert rl.check_concurrent_runs(org_id) is False
    rl.record_run_end(org_id)
    assert rl.check_concurrent_runs(org_id) is True

def test_login_attempts_limit():
    rl = RateLimiter()
    ip = "127.0.0.1"
    for _ in range(20):
        rl.record_login_attempt(ip)
    assert rl.check_login_attempts(ip) is False

def test_hourly_starts_limit():
    rl = RateLimiter()
    org_id = "org-1"
    for _ in range(20):
        rl.record_run_start(org_id)
    assert rl.check_hourly_starts(org_id) is False

def test_registration_attempts_limit():
    rl = RateLimiter()
    ip = "1.1.1.1"
    for _ in range(5):
        rl.record_registration_attempt(ip)
    assert rl.check_registration_attempts(ip) is False
