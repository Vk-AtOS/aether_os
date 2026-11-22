"""P05 page generation limits (KAN-214).

Entity pages are independent, so p05 writes them concurrently, but never more
than PIPELINE_PAGE_CONCURRENCY at once (default 3): the provider and the org
have their own rate limits, and an unbounded fan-out turns into 429s that
silently degrade pages to templates. A 429 is retried with backoff.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

DEFAULT_PAGE_CONCURRENCY = 3
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BASE_DELAY_S = 5.0


def page_concurrency() -> int:
    """PIPELINE_PAGE_CONCURRENCY, at least 1; a bad value falls back to the default."""
    raw = os.environ.get("PIPELINE_PAGE_CONCURRENCY", str(DEFAULT_PAGE_CONCURRENCY))
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("PIPELINE_PAGE_CONCURRENCY=%r is not an integer - using %d", raw, DEFAULT_PAGE_CONCURRENCY)
        return DEFAULT_PAGE_CONCURRENCY


def page_semaphore() -> asyncio.Semaphore:
    """One semaphore per page-writing pass; all its pages share the same limit."""
    return asyncio.Semaphore(page_concurrency())


def is_rate_limited(exc: BaseException) -> bool:
    """True for a provider 429 / quota error, however the client worded it."""
    text = str(exc).lower()
    return (getattr(exc, "status_code", None) == 429 or "429" in text
            or "rate limit" in text or "rate_limit" in text or "too many requests" in text)


async def call_with_backoff(make_call: Callable[[], Awaitable[Any]], what: str) -> Any:
    """Await make_call(); on a 429 wait 5s, 10s, 20s and try again, then give up (re-raise).

    The caller holds a page slot while we sleep, which is the point: a rate-limited
    provider gets fewer concurrent requests, not the same number again.
    """
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return await make_call()
        except Exception as exc:
            if not is_rate_limited(exc) or attempt == RATE_LIMIT_RETRIES:
                raise
            delay = RATE_LIMIT_BASE_DELAY_S * (2 ** attempt)
            logger.warning("p05: %s rate limited (attempt %d), retrying in %.0fs: %s", what, attempt + 1, delay, exc)
            await asyncio.sleep(delay)
