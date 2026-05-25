import pytest
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aether_os.core.rate_limiter import RateLimiter


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_concurrent_runs_limit():
    rl = RateLimiter()
    org_id = "test-org"
    for _ in range(5):
        _run(rl.record_run_start(org_id))
    assert _run(rl.check_concurrent_runs(org_id)) is False
    _run(rl.record_run_end(org_id))
    assert _run(rl.check_concurrent_runs(org_id)) is True


def test_login_attempts_limit():
    rl = RateLimiter()
    ip = "127.0.0.1"
    for _ in range(20):
        _run(rl.record_login_attempt(ip))
    assert _run(rl.check_login_attempts(ip)) is False


def test_hourly_starts_limit():
    rl = RateLimiter()
    org_id = "org-1"
    for _ in range(20):
        _run(rl.record_run_start(org_id))
    assert _run(rl.check_hourly_starts(org_id)) is False


def test_registration_attempts_limit():
    rl = RateLimiter()
    ip = "1.1.1.1"
    for _ in range(5):
        _run(rl.record_registration_attempt(ip))
    assert _run(rl.check_registration_attempts(ip)) is False
