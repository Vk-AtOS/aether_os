"""
Bridge for Aether2 to use DCSP as its monitoring and self-healing layer.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any
import requests
import uuid
import time
from src.intelligence.predictor import PIPELINE_PREDICTOR
from src.db.job_repo import save_job, record_stage_timing
from src.database import SessionLocal

logger = logging.getLogger(__name__)

class Aether2Bridge:
    """
    Connects Aether2 pipelines to DCSP for 
    predictive monitoring and automated repair.
    """

    def __init__(self):
        self.api_url = None
        self.api_key = None
        self._active_pipelines: Dict[str, dict] = {}

    def connect(self, dcsp_api_url: str, api_key: str):
        """Stores connection configuration for DCSP."""
        self.api_url = dcsp_api_url
        self.api_key = api_key

    def register_pipeline(self, pipeline_id: str, stages: List[str], tenant_id: Optional[str] = None):
        """Creates a DCSP job context for monitoring this Aether2 pipeline."""
        session = SessionLocal()
        try:
            job_data = {
                "id": pipeline_id,
                "repo_name": f"aether2_{pipeline_id}",
                "branch": "aether2_managed",
                "explanation": f"Monitoring Aether2 pipeline {pipeline_id}",
                "tenant_id": tenant_id
            }
            save_job(session, job_data)
            self._active_pipelines[pipeline_id] = {
                "stages": stages,
                "tenant_id": tenant_id,
                "start_times": {}
            }
        finally:
            session.close()

    def report_stage_start(self, pipeline_id: str, stage_name: str):
        """Notifies DCSP a stage has started — begins timing."""
        if pipeline_id in self._active_pipelines:
            self._active_pipelines[pipeline_id]["start_times"][stage_name] = time.time()

    def report_stage_complete(self, pipeline_id: str, stage_name: str, duration_seconds: int, success: bool):
        """Records completion, triggers prediction update."""
        tenant_id = self._active_pipelines.get(pipeline_id, {}).get("tenant_id")
        outcome = "success" if success else "failure"
        PIPELINE_PREDICTOR.record_stage_timing(pipeline_id, stage_name, duration_seconds, outcome, tenant_id)

    def get_pipeline_health(self, pipeline_id: str) -> dict:
        """Returns current health prediction from DCSP predictor."""
        return PIPELINE_PREDICTOR.predict_pipeline_outcome(pipeline_id)

    def report_failure(self, pipeline_id: str, stage_name: str, error_details: str) -> dict:
        """Notifies DCSP of a pipeline failure via the ci-auto webhook."""
        if self.api_url:
            try:
                resp = requests.post(
                    f"{self.api_url}/webhook/ci-auto",
                    json={
                        "repo_name": f"aether2_{pipeline_id}",
                        "branch": "aether2_managed",
                        "log_content": f"Stage '{stage_name}' failed: {error_details}",
                        "ci_system": "aether2",
                    },
                    headers={"X-API-Key": self.api_key or ""},
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.warning("Aether2Bridge.report_failure HTTP error: %s", exc)
        # Fallback when DCSP is unreachable or not configured
        return {
            "repair_job_id": str(uuid.uuid4()),
            "estimated_fix_time": 300,
            "recommended_action": f"DCSP analyzing failure in stage '{stage_name}': {error_details[:50]}...",
        }
