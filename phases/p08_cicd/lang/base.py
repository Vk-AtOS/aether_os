"""
Base classes for language adapters.
Migrated from DCSP src/lang/base.py.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LanguageFailure:
    """Standardized language failure information."""

    language: str
    error_type: str
    error_message: str
    failing_file: str
    failing_function: str
    line_number: int
    raw_traceback: str


class LanguageAdapter(ABC):
    """Abstract base class for language-specific failure parsers."""

    @abstractmethod
    def parse(self, log_output: str) -> Optional[LanguageFailure]:
        """
        Parse raw log output into a standardized LanguageFailure.
        Returns None if this adapter cannot handle the log.
        """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Name of the programming language (e.g., 'python')."""

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        """Common file extensions for this language."""
