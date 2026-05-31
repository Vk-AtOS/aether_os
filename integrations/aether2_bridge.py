"""
AetherOS → DCSP bridge client.

Sends pipeline telemetry to a DCSP instance (if DCSP_URL is set) so that
DCSP can provide predictive monitoring and automated repair.

All network calls are dispatched on a daemon thread so they never block
the async pipeline loop.  Every public method catches and logs all exceptions.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Aether2Bridge:
    """Lightweight HTTP client that reports AetherOS pipeline events to DCSP."""

    def __init__(self) -> None:
        self.api_url: Optional[str] = None
        self.api_key: Optional[str] = None
        self._stage_starts: Dict[str, float] = {}

    def connect(self, dcsp_api_url: str, api_key: str) -> None:
        self.api_url = dcsp_api_url.rstrip("/")
        self.api_key = api_key

    def register_pipeline(self, pipeline_id: str, stages: List[str]) -> None:
        self._fire(
            "POST",
            "/api/pipelines/register",
            {
                "pipeline_id": pipeline_id,
                "stages": stages,
                "source": "aetheros",
            },
        )

    def report_stage_start(self, pipeline_id: str, stage_name: str) -> None:
        self._stage_starts[f"{pipeline_id}:{stage_name}"] = time.time()

    def report_stage_complete(
        self,
        pipeline_id: str,
        stage_name: str,
        duration_seconds: int,
        success: bool,
    ) -> None:
        self._fire(
            "POST",
            "/api/pipelines/stage",
            {
                "pipeline_id": pipeline_id,
                "stage_name": stage_name,
                "duration_seconds": duration_seconds,
                "outcome": "success" if success else "failure",
            },
        )

    def report_failure(self, pipeline_id: str, stage_name: str, error_details: str) -> dict:
        self._fire(
            "POST",
            "/webhook/ci-auto",
            {
                "repo_name": f"aether2_{pipeline_id}",
                "branch": "aether2_managed",
                "log_content": f"Stage '{stage_name}' failed: {error_details}",
                "ci_system": "aether2",
            },
        )
        return {"pipeline_id": pipeline_id, "stage_name": stage_name}

    # ── internal ──────────────────────────────────────────────────────────────

    def _fire(self, method: str, path: str, payload: dict) -> None:
        """Dispatch an HTTP request on a daemon thread (fire-and-forget)."""
        if not self.api_url:
            return
        url = f"{self.api_url}{path}"
        headers = {"X-API-Key": self.api_key or "", "Content-Type": "application/json"}
        t = threading.Thread(target=self._send, args=(method, url, headers, payload), daemon=True)
        t.start()

    def _send(self, method: str, url: str, headers: dict, payload: dict) -> None:
        try:
            import requests
            resp = requests.request(method, url, json=payload, headers=headers, timeout=10)
            if resp.status_code >= 400:
                logger.debug("Aether2Bridge %s %s → %d", method, url, resp.status_code)
        except Exception as exc:
            logger.debug("Aether2Bridge %s %s non-fatal: %s", method, url, exc)
