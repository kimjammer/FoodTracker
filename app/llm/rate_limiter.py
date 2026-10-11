"""
Async Rate Limiter and Exponential Backoff for Gemini API calls.
Protects against the 15 RPM free tier limit.
"""

import asyncio
import inspect
import logging
import time
from typing import Any, Callable, List, Optional

from google.genai import errors

logger = logging.getLogger(__name__)


async def _maybe_await(func: Optional[Callable], *args: Any, **kwargs: Any) -> Any:
    """Helper to call either sync or async callbacks safely."""
    if func is None:
        return None
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)


def is_rate_limit_error(exc: Exception) -> bool:
    """Detect if an exception is a Google GenAI rate limit (HTTP 429 or quota limit)."""
    if isinstance(exc, errors.APIError) and getattr(exc, "code", None) == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg or "rate limit" in msg


class AsyncRateLimiter:
    """
    Token-bucket / sliding window rate limiter with concurrency lock
    and exponential backoff retry.
    """

    def __init__(
        self,
        max_requests: Optional[int] = None,
        window_seconds: float = 60.0,
        min_interval: Optional[float] = None,
    ):
        from config import settings

        self.max_requests = max_requests if max_requests is not None else settings.gemini_max_rpm
        self.window_seconds = window_seconds
        self.min_interval = min_interval if min_interval is not None else settings.gemini_min_interval
        self._timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self, on_throttle: Optional[Callable[[float], Any]] = None) -> float:
        """
        Wait until a request slot is available in the sliding window.
        If a delay is required and on_throttle is provided, on_throttle(wait_seconds) is invoked.
        Returns the duration waited.
        """
        async with self._lock:
            now = time.monotonic()
            # Prune timestamps older than window
            self._timestamps = [t for t in self._timestamps if now - t < self.window_seconds]

            wait = 0.0
            # Check window capacity limit (max 14 per 60s)
            if len(self._timestamps) >= self.max_requests:
                oldest = self._timestamps[0]
                window_wait = (oldest + self.window_seconds) - now + 0.1
                if window_wait > wait:
                    wait = window_wait

            # Check minimum interval spacing between consecutive calls
            if self._timestamps:
                spacing_wait = (self._timestamps[-1] + self.min_interval) - now
                if spacing_wait > wait:
                    wait = spacing_wait

            if wait > 0:
                logger.warning(f"RateLimiter pacing request: waiting {wait:.2f}s to respect 15 RPM limit")
                if on_throttle and wait >= 1.0:
                    await _maybe_await(on_throttle, wait)
                await asyncio.sleep(wait)
                now = time.monotonic()

            self._timestamps.append(now)
            return wait

    async def execute_with_retry(
        self,
        coro_func: Callable[..., Any],
        *args: Any,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
        max_retries: int = 4,
        base_delay: float = 4.0,
        **kwargs: Any,
    ) -> Any:
        """
        Execute an async Gemini API call with sliding-window pacing and exponential backoff retry.
        If on_rate_limit is provided, on_rate_limit(attempt, delay_seconds) will be called.
        """
        for attempt in range(max_retries + 1):
            await self.acquire(
                on_throttle=lambda wait: on_rate_limit(0, wait) if on_rate_limit and wait > 2.0 else None
            )
            try:
                return await coro_func(*args, **kwargs)
            except Exception as e:
                if is_rate_limit_error(e) and attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Hit Gemini rate limit (attempt {attempt + 1}/{max_retries}). "
                        f"Backing off for {delay:.1f}s. Error: {e}"
                    )
                    if on_rate_limit:
                        await _maybe_await(on_rate_limit, attempt + 1, delay)
                    await asyncio.sleep(delay)
                else:
                    raise


rate_limiter = AsyncRateLimiter()
