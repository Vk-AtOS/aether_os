"""
AetherOS Live Build Monitor — starts a pipeline run on the VPS and tails logs.
Reports errors, warnings, and phase timing.

Usage:
    python3 tests/monitor_live_build.py
"""
import asyncio
import time
from datetime import datetime

import httpx

BASE = "http://REDACTED_IP"
EMAIL = "demo@aetheros.ai"
PASSWORD = "demo1234"

BUILD_SPEC = "Build a minimal todo list REST API with FastAPI and SQLite. Include GET /todos, POST /todos, DELETE /todos/{id}."

issues: list[dict] = []
phase_times: list[dict] = []


def note(severity: str, msg: str):
    icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(severity, "•")
    print(f"  {icon} [{severity}] {msg}")
    issues.append({"severity": severity, "msg": msg, "time": datetime.now().isoformat()})


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # Login
        print("Logging in...")
        r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        if r.status_code != 200:
            note("ERROR", f"Login failed: {r.status_code} {r.text[:200]}")
            return
        token = r.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}
        note("INFO", "Login OK")

        # Start pipeline run
        print("\nStarting pipeline run...")
        r = await client.post("/api/factory/start", json={"raw_input": BUILD_SPEC}, headers=headers)
        if r.status_code not in (200, 201):
            note("ERROR", f"Start failed: {r.status_code} {r.text[:300]}")
            return
        run_id = r.json().get("run_id")
        note("INFO", f"Run started: {run_id}")

        # Poll status
        print(f"\nMonitoring run {run_id}...")
        start_time = time.time()
        last_phase = None
        phase_start = start_time
        timeout = 600  # 10 minutes max
        poll_interval = 8

        while time.time() - start_time < timeout:
            await asyncio.sleep(poll_interval)
            try:
                r = await client.get(f"/api/factory/runs/{run_id}", headers=headers)
                if r.status_code != 200:
                    note("WARN", f"Poll returned {r.status_code}")
                    continue
                data = r.json()
            except Exception as e:
                note("WARN", f"Poll exception: {e}")
                continue

            status = data.get("status", "?")
            current_phase = data.get("current_phase", "?")
            elapsed = int(time.time() - start_time)

            if current_phase != last_phase:
                if last_phase is not None:
                    phase_elapsed = int(time.time() - phase_start)
                    phase_times.append({"phase": last_phase, "seconds": phase_elapsed})
                    print(f"  Phase {last_phase} took {phase_elapsed}s")
                phase_start = time.time()
                last_phase = current_phase
                print(f"\n[{elapsed}s] Phase: {current_phase} | Status: {status}")

            # Check for error signals
            msg = data.get("message", "") or ""
            if "error" in msg.lower() or "failed" in msg.lower() or "exception" in msg.lower():
                note("WARN", f"Message contains error signal: {msg[:120]}")

            if status in ("completed", "failed", "cancelled"):
                phase_elapsed = int(time.time() - phase_start)
                if last_phase:
                    phase_times.append({"phase": last_phase, "seconds": phase_elapsed})
                total = int(time.time() - start_time)
                print(f"\nRun finished in {total}s — status: {status}")
                if status == "completed":
                    note("INFO", f"Run COMPLETED in {total}s")
                    # Check artifacts
                    try:
                        ra = await client.get(f"/api/factory/runs/{run_id}/artifacts", headers=headers)
                        if ra.status_code == 200:
                            arts = ra.json()
                            count = len(arts) if isinstance(arts, list) else arts.get("count", "?")
                            note("INFO", f"Artifacts: {count} files generated")
                        else:
                            note("WARN", f"Artifacts endpoint: {ra.status_code}")
                    except Exception as e:
                        note("WARN", f"Artifact check failed: {e}")
                else:
                    note("ERROR", f"Run ended with status={status}: {msg[:200]}")
                break
        else:
            note("ERROR", f"Run timed out after {timeout}s — still in phase {last_phase}")

    # Report
    print("\n" + "="*60)
    print("PHASE TIMING:")
    for pt in phase_times:
        flag = " ⚠️ SLOW" if pt["seconds"] > 120 else ""
        print(f"  {pt['phase']}: {pt['seconds']}s{flag}")

    print("\nISSUES FOUND:")
    errors = [i for i in issues if i["severity"] == "ERROR"]
    warns = [i for i in issues if i["severity"] == "WARN"]
    if not errors and not warns:
        print("  None — clean run!")
    for i in errors + warns:
        print(f"  [{i['severity']}] {i['msg']}")

    return {
        "run_id": run_id if "run_id" in dir() else None,
        "phases": phase_times,
        "issues": issues,
    }


if __name__ == "__main__":
    asyncio.run(run())
