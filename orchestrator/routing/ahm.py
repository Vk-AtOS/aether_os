"""
AetherOS — Adaptive Hybrid Mesh (AHM): LLM Provider Health Tracker

Tracks per-provider success/failure rates with exponential decay so the
ModelRouter can prefer healthy providers over degraded ones — beyond the
binary dead/alive state of the existing circuit-breaker.

Key properties:
  - No network calls, fully in-process
  - Exponential decay: a failure from 10 minutes ago has half the weight
    of a failure from 5 minutes ago
  - Thread-safe enough for asyncio (single event loop, no concurrent writes)
  - ModelRouter calls record_success/record_failure after every attempt;
    calls reorder_chain before iterating providers

Integration point: core/model_router.py imports default_ahm at call time
(lazy import to avoid circular deps at module load).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Half-life for exponential decay of event counts (seconds).
# A failure 10 min ago has ~50% weight of a failure right now.
_SCORE_HALFLIFE_S: float = 600.0


@dataclass
class ProviderHealth:
    """Rolling health score for a single LLM provider."""

    provider: str
    score: float = 1.0          # 0.0 (dead) → 1.0 (perfect)
    recent_successes: float = 0.0
    recent_failures: float = 0.0
    last_failure_reason: str = ""
    _last_updated: float = field(default_factory=time.time, repr=False)

    def record_success(self) -> None:
        self._decay()
        self.recent_successes += 1.0
        self._recalculate()

    def record_failure(self, reason: str = "") -> None:
        self._decay()
        self.recent_failures += 1.0
        self.last_failure_reason = reason
        self._recalculate()

    def _decay(self) -> None:
        """Exponential decay: older events count for less."""
        now = time.time()
        elapsed = now - self._last_updated
        if elapsed > 0:
            # Multiplicative decay: counts halve every _SCORE_HALFLIFE_S seconds
            factor = 0.5 ** (elapsed / _SCORE_HALFLIFE_S)
            self.recent_successes *= factor
            self.recent_failures *= factor
        self._last_updated = now

    def _recalculate(self) -> None:
        total = self.recent_successes + self.recent_failures
        if total < 0.5:  # effectively zero after decay
            self.score = 1.0
            return
        self.score = max(0.0, min(1.0, self.recent_successes / total))
        if self.score < 0.5:
            logger.warning(
                "[AHM] Provider %r degraded: score=%.2f (s=%.1f f=%.1f reason=%r)",
                self.provider, self.score,
                self.recent_successes, self.recent_failures,
                self.last_failure_reason or "—",
            )

    @property
    def is_degraded(self) -> bool:
        return self.score < 0.5


class AdaptiveHybridMesh:
    """
    LLM provider health tracker.

    Called by ModelRouter after every LLM attempt (success or failure) to
    maintain rolling health scores per provider. `reorder_chain()` sorts
    the fallback chain so healthy providers run first, giving the system
    adaptive routing without any external config changes.
    """

    def __init__(self) -> None:
        self._health: Dict[str, ProviderHealth] = {}
        logger.info("[AHM] Adaptive Hybrid Mesh initialised")

    def _get(self, provider: str) -> ProviderHealth:
        if provider not in self._health:
            self._health[provider] = ProviderHealth(provider=provider)
        return self._health[provider]

    def record_success(self, provider: str) -> None:
        """Call after every successful LLM response."""
        h = self._get(provider)
        h.record_success()
        logger.debug("[AHM] %r success → score=%.2f", provider, h.score)

    def record_failure(self, provider: str, reason: str = "") -> None:
        """Call after every failed LLM attempt (timeout, error, placeholder)."""
        h = self._get(provider)
        h.record_failure(reason)
        logger.debug("[AHM] %r failure → score=%.2f (%s)", provider, h.score, reason[:80])

    def reorder_chain(self, chain: list) -> list:
        """
        Re-sort the ModelRouter fallback chain so healthy providers run first.

        Providers with score >= 0.5 maintain their relative order among
        themselves. Degraded providers (score < 0.5) are pushed to the end,
        also maintaining relative order among themselves.

        If no health data is available yet, the original chain is returned
        unchanged so first-run behaviour is identical to the pre-AHM state.
        """
        if not self._health:
            return chain

        healthy, degraded = [], []
        for spec in chain:
            h = self._health.get(spec.provider)
            if h and h.is_degraded:
                degraded.append(spec)
            else:
                healthy.append(spec)

        reordered = healthy + degraded
        if degraded:
            logger.info(
                "[AHM] Chain reordered — healthy: %s | degraded: %s",
                [s.provider for s in healthy],
                [s.provider for s in degraded],
            )
        return reordered

    def get_health_scores(self) -> Dict[str, float]:
        """Return a snapshot of current health scores (for metrics/UI)."""
        return {p: h.score for p, h in self._health.items()}

    def get_degraded_providers(self) -> List[str]:
        """Return list of currently degraded provider names."""
        return [p for p, h in self._health.items() if h.is_degraded]

    def reset(self, provider: Optional[str] = None) -> None:
        """Reset health state — useful after operator remediation."""
        if provider:
            self._health.pop(provider, None)
            logger.info("[AHM] Reset health for provider %r", provider)
        else:
            self._health.clear()
            logger.info("[AHM] Reset health for all providers")


# Process-level singleton — imported lazily by core/model_router.py
default_ahm = AdaptiveHybridMesh()
