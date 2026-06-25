"""
CI Adapter plugin system for DCSP.
"""

from __future__ import annotations

from src.adapters.base import CIAdapter, CIFailureEvent
from src.adapters.detector import detect_adapter

__all__ = ["CIAdapter", "CIFailureEvent", "detect_adapter"]
