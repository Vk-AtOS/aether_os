"""The whole-build time limit, shared by the pipeline (which enforces it) and the workloop monitor (which reports runs
past it as hung), so the two never disagree.

Default 120 minutes. The old default of 30 was set before builds ran on a real model: production acceptance run 11
(22 Nov 2026, NVIDIA Nemotron) took 29 minutes for stages s01 to s05 alone (s04 frontend about 14), and the build was
stopped 5 minutes into Stage 6 test repair with a message blaming the model provider. Override with
PIPELINE_TIMEOUT_MINUTES.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_TIMEOUT_MINUTES = 120.0


def pipeline_timeout_seconds() -> float:
    raw = os.environ.get("PIPELINE_TIMEOUT_MINUTES", "")
    if not raw.strip():
        return DEFAULT_PIPELINE_TIMEOUT_MINUTES * 60
    try:
        minutes = float(raw)
    except ValueError as exc:
        logger.warning("PIPELINE_TIMEOUT_MINUTES=%r is not a number (%s); using %s", raw, exc,
                       DEFAULT_PIPELINE_TIMEOUT_MINUTES)
        return DEFAULT_PIPELINE_TIMEOUT_MINUTES * 60
    if minutes <= 0:
        logger.warning("PIPELINE_TIMEOUT_MINUTES=%r must be positive; using %s", raw, DEFAULT_PIPELINE_TIMEOUT_MINUTES)
        return DEFAULT_PIPELINE_TIMEOUT_MINUTES * 60
    return minutes * 60
