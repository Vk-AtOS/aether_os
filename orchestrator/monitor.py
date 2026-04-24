from __future__ import annotations
import threading
import time
from typing import Dict, Any, Optional
import logging
logger = logging.getLogger(__name__)
from aether_os.core.audit.ledger import get_ledger


class DCSPBridge:
    _instance: Optional[DCSPBridge] = None

    def __init__(self):
        self.ledger = get_ledger()
        self._monitoring = False
        self._thread: Optional[threading.Thread] = None
        self._run_id: Optional[str] = None
        self._thresholds: Dict[str, int] = {}
        self._current_stage: Optional[str] = None
        self._stage_start_time: float = 0
        self._lock = threading.Lock()

    def start_monitoring(self, run_id: str, thresholds: Dict[str, int]):
        with self._lock:
            if self._monitoring:
                self.stop_monitoring()
            
            self._run_id = run_id
            self._thresholds = thresholds
            self._monitoring = True
            self._current_stage = None
            self._stage_start_time = time.time()
            
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()

    def stop_monitoring(self):
        with self._lock:
            self._monitoring = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def set_stage(self, stage: str):
        with self._lock:
            self._current_stage = stage
            self._stage_start_time = time.time()

    def check_pipeline_health(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            if not self._monitoring or self._run_id != run_id:
                return {"status": "unknown"}
            
            elapsed = time.time() - self._stage_start_time
            current_limit = self._thresholds.get(self._current_stage, 300) if self._current_stage else 300
            
            return {
                "status": "healthy" if elapsed < current_limit else "stalled",
                "stage": self._current_stage,
                "elapsed": elapsed,
                "limit": current_limit
            }

    def _monitor_loop(self):
        while True:
            with self._lock:
                if not self._monitoring:
                    break
                stage = self._current_stage
                start_time = self._stage_start_time
                thresholds = self._thresholds
                run_id = self._run_id

            if stage:
                elapsed = time.time() - start_time
                limit = thresholds.get(stage, 300)

                if elapsed > limit * 2:
                    # Critical
                    self.ledger.log_event(run_id, "DCSP", "stall_critical", 
                                          {"stage": stage, "elapsed": elapsed, "limit": limit})
                    print(f"\n[DCSP] CRITICAL: Pipeline stalled at {stage} for {elapsed:.1f}s (Limit: {limit}s)")
                    # In a real system, we might attempt restart here
                elif elapsed > limit:
                    # Warning
                    self.ledger.log_event(run_id, "DCSP", "stall_warning", 
                                          {"stage": stage, "elapsed": elapsed, "limit": limit})
                    print(f"\n[DCSP] WARNING: {stage} is taking longer than expected ({elapsed:.1f}s > {limit}s)")

            time.sleep(5)


def get_dcsp_bridge() -> DCSPBridge:
    if DCSPBridge._instance is None:
        DCSPBridge._instance = DCSPBridge()
    return DCSPBridge._instance
