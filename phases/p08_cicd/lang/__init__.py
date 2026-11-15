"""
Language adapter plugin system for the AetherOS CI/CD phase.
"""

from __future__ import annotations

import logging

from aether_os.phases.p08_cicd.lang.base import LanguageAdapter, LanguageFailure
from aether_os.phases.p08_cicd.lang.detector import detect_language_adapter

logger = logging.getLogger(__name__)

__all__ = ["LanguageAdapter", "LanguageFailure", "detect_language_adapter"]
