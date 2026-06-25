"""
Language adapter detection logic.
"""

from __future__ import annotations

from typing import Optional
from src.lang.base import LanguageAdapter
from src.lang.python_adapter import PythonAdapter
from src.lang.javascript_adapter import JavaScriptAdapter
from src.lang.java_adapter import JavaAdapter


def detect_language_adapter(log_output: str) -> Optional[LanguageAdapter]:
    """
    Tries each available language adapter in order and returns the first one that matches the log.
    """
    adapters = [
        PythonAdapter(),
        JavaScriptAdapter(),
        JavaAdapter(),
    ]

    for adapter in adapters:
        if adapter.parse(log_output) is not None:
            return adapter

    return None
