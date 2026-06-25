"""
Language Adapter plugin system for DCSP.
"""

from __future__ import annotations

from src.lang.base import LanguageAdapter, LanguageFailure
from src.lang.detector import detect_language_adapter

__all__ = ["LanguageAdapter", "LanguageFailure", "detect_language_adapter"]
