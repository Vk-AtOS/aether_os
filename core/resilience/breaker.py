"""Circuit breaker: closed -> open after N consecutive failures -> half-open after a cool-down -> closed on one success.

State is per process. Each worker learns about a failing dependency by its own failures (at most `failure_threshold` slow
calls per worker), which is the standard trade-off; a shared state would itself depend on Redis, one of the things that fails.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Awaitable, Callable, Dict, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitOpen(Exception):
    """The breaker is open: the call was not attempted."""

    def __init__(self, name: str, retry_in: float) -> None:
        super().__init__(f"{name} is unavailable (circuit open, retry in {retry_in:.0f}s)")
        self.name, self.retry_in = name, retry_in


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, reset_after_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.name, self.failure_threshold, self.reset_after_s, self._clock = name, failure_threshold, reset_after_s, clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._probing = False      # half-open lets exactly one trial call through
        self._state = CLOSED
        self.opened_total = 0
        self.last_error = ""

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> str:
        if self._state == OPEN and self._clock() - self._opened_at >= self.reset_after_s:
            self._state = HALF_OPEN
        return self._state

    def before_call(self) -> None:
        """Raise CircuitOpen unless a call may go ahead. In half-open exactly one caller is the probe."""
        with self._lock:
            st = self._state_locked()
            if st == CLOSED:
                return
            if st == HALF_OPEN and not self._probing:
                self._probing = True
                return
            raise CircuitOpen(self.name, max(0.0, self.reset_after_s - (self._clock() - self._opened_at)))

    def record_success(self) -> None:
        with self._lock:
            if self._state != CLOSED:
                logger.info("circuit %s closed again", self.name)
            self._state, self._failures, self._probing = CLOSED, 0, False

    def record_failure(self, error: object = "") -> None:
        with self._lock:
            self._failures += 1
            self.last_error = str(error)[:200]
            if self._state == HALF_OPEN or self._failures >= self.failure_threshold:
                if self._state != OPEN:
                    self.opened_total += 1
                    logger.warning("circuit %s OPEN after %d failures: %s", self.name, self._failures, self.last_error)
                self._state, self._opened_at, self._probing = OPEN, self._clock(), False

    async def call(self, fn: Callable[[], Awaitable[T]], *, is_failure: Callable[[BaseException], bool] = lambda e: True) -> T:
        """Run `fn` through the breaker. Exceptions for which `is_failure` is False (e.g. a 404) do not count."""
        self.before_call()
        try:
            result = await fn()
        except BaseException as e:  # CancelledError must free the half-open probe too
            if isinstance(e, Exception) and is_failure(e):
                self.record_failure(f"{type(e).__name__}: {e}")
            else:
                with self._lock:
                    self._probing = False
            raise
        self.record_success()
        return result

    def snapshot(self) -> Dict[str, object]:
        return {"name": self.name, "state": self.state, "failures": self._failures, "opened_total": self.opened_total,
                "last_error": self.last_error}


_registry: Dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(name, **kwargs)
        return _registry[name]


def all_breakers() -> Dict[str, CircuitBreaker]:
    with _registry_lock:
        return dict(_registry)
