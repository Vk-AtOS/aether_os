"""The whole-build limit: one setting for the pipeline and the hung-run monitor (acceptance run 11, 22 Nov 2026)."""
from __future__ import annotations

import time

import pytest

from aether_os.core import run_limits
from aether_os.core.workloop_monitor import WorkloopMonitor


@pytest.mark.parametrize("raw, minutes", [("", 120), ("45", 45), ("0.5", 0.5), ("abc", 120), ("0", 120), ("-3", 120)])
def test_limit_reads_the_setting_and_falls_back_to_120(monkeypatch, raw, minutes):
    monkeypatch.setenv("PIPELINE_TIMEOUT_MINUTES", raw)
    assert run_limits.pipeline_timeout_seconds() == minutes * 60


def test_default_covers_a_measured_real_model_build(monkeypatch):
    monkeypatch.delenv("PIPELINE_TIMEOUT_MINUTES", raising=False)
    # s01 to s05 alone took 29 minutes on production; the old 30-minute default stopped Stage 6.
    assert run_limits.pipeline_timeout_seconds() >= 90 * 60


def test_hung_runs_use_the_same_limit(monkeypatch):
    monkeypatch.setenv("PIPELINE_TIMEOUT_MINUTES", "60")
    now = time.time()
    base = {"current_phase": "", "message": "", "finished_at": None, "domain": ""}
    runs = [{**base, "status": "running", "started_at": now - 45 * 60},     # under the limit: not hung
            {**base, "status": "running", "started_at": now - 75 * 60}]     # past it: hung
    assert WorkloopMonitor()._extract_patterns(runs)["hung_count"] == 1
