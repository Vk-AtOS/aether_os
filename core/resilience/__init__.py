"""Failure containment: circuit breakers, bulkheads and a component health view (KAN-49).

A breaker stops calling a dependency that keeps failing (fail fast, 503) so threads and connections are not held by it;
a bulkhead caps how many calls one class of work may have in flight so it cannot starve the others;
`health.snapshot()` reports which components are degraded, for /readyz and the dashboard.
"""
from aether_os.core.resilience import breaker as _breaker, bulkhead as _bulkhead
from aether_os.core.resilience.breaker import CircuitBreaker, CircuitOpen, all_breakers, get_breaker  # noqa: F401
from aether_os.core.resilience.bulkhead import Bulkhead, BulkheadFull, all_bulkheads, get_bulkhead  # noqa: F401


def reset_all() -> None:
    """Forget every breaker and bulkhead (tests, and a deliberate operator reset)."""
    _breaker._registry.clear()
    _bulkhead._registry.clear()
