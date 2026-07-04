"""
Base classes for CI adapters.
Base classes for CI adapters in the AetherOS CI/CD phase.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CIFailureEvent:
    """Standardized CI failure event."""

    repo_name: str
    branch: str
    commit_sha: str
    log_output: str
    ci_system: str
    raw_payload: dict[str, Any]


class CIAdapter(ABC):
    """Abstract base class for CI-specific adapters."""

    @abstractmethod
    def parse(self, payload: dict[str, Any]) -> Optional[CIFailureEvent]:
        """
        Parse raw payload into a standardized CIFailureEvent.
        Returns None if this adapter cannot handle the payload.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the CI system (e.g., 'github_actions')."""
