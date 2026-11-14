"""KAN-170: one failed DB probe or a full disk must never trigger a restore."""
import asyncio

from aether_os.core.guardian import watchdog as wd

DB = {"event_type": "service_crash", "severity": "critical", "detail": {"service": "database"}}
DISK = {"event_type": "service_crash", "severity": "critical", "detail": {"service": "disk"}}


def test_single_db_failure_is_suppressed_and_streak_resets():
    w = wd.GuardianWatchdog()
    assert w._gate_db_failures([dict(DB)]) == []
    assert w._gate_db_failures([]) == []
    assert w._db_failures == 0


def test_consecutive_db_failures_become_a_crash():
    w = wd.GuardianWatchdog()
    out = []
    for _ in range(wd._DB_FAILS_BEFORE_CRASH):
        out = w._gate_db_failures([dict(DB)])
    assert out == [DB]


def test_disk_pressure_never_recovers_or_snapshots(monkeypatch):
    w = wd.GuardianWatchdog()
    calls = []

    async def fake_persist(events): return ["id1"]
    async def fake_dup(e): return False
    async def fake_snap(trigger): calls.append(("snap", trigger))
    async def fake_rec(i): calls.append(("recover", i))
    monkeypatch.setattr(w, "_persist_events", fake_persist)
    monkeypatch.setattr(w, "_is_duplicate", fake_dup)
    monkeypatch.setattr(w, "_take_snapshot", fake_snap)
    monkeypatch.setattr(w, "_run_recovery", fake_rec)

    async def go():
        await w._process_events([dict(DISK)])
        await w._process_events([dict(DB)])
        await asyncio.sleep(0)
    asyncio.run(go())
    assert ("recover", "id1") in calls and calls.count(("snap", "pre_threat")) == 1
    assert len([c for c in calls if c[0] == "recover"]) == 1
