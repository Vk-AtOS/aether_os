"""
Language adapter detection logic.
"""

from __future__ import annotations

from typing import Optional
from aether_os.phases.p08_cicd.lang.base import LanguageAdapter
from aether_os.phases.p08_cicd.lang.python import PythonAdapter
from aether_os.phases.p08_cicd.lang.javascript import JavaScriptAdapter
from aether_os.phases.p08_cicd.lang.java import JavaAdapter


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
