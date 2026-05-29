"""
AetherOS Guardian — Autonomous self-monitoring, threat detection, and self-healing.

Three components:
  ThreatDetector  — watches auth failures, file integrity, service health
  SnapshotManager — takes/restores DB snapshots before and after incidents
  AutoRecovery    — restores from snapshots, verifies health post-restore
  GuardianWatchdog — background loop that ties them together
"""
from .watchdog import GuardianWatchdog, get_watchdog

__all__ = ["GuardianWatchdog", "get_watchdog"]
