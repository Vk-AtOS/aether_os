"""
Rate limiter for DCSP API.
Prevents webhook abuse with a simple in-memory sliding window.
"""

from __future__ import annotations

import time
import threading
from typing import Dict, List


class RateLimiter:
    """Simple thread-safe rate limiter."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, identifier: str) -> bool:
        """Checks if a request from this identifier is allowed."""
        now = time.time()
        with self._lock:
            if identifier not in self._requests:
                self._requests[identifier] = [now]
                return True

            # Filter out old timestamps
            self._requests[identifier] = [
                t for t in self._requests[identifier]
                if now - t < self.window_seconds
            ]

            if len(self._requests[identifier]) < self.max_requests:
                self._requests[identifier].append(now)
                return True
            
            return False

    def get_stats(self, identifier: str) -> dict:
        """Returns stats for an identifier."""
        now = time.time()
        with self._lock:
            timestamps = [
                t for t in self._requests.get(identifier, [])
                if now - t < self.window_seconds
            ]
            return {
                "identifier": identifier,
                "count": len(timestamps),
                "window_seconds": self.window_seconds,
                "allowed": len(timestamps) < self.max_requests
            }


# Global singleton
GLOBAL_RATE_LIMITER = RateLimiter()
