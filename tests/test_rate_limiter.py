import asyncio
from unittest.mock import AsyncMock

import pytest

from app.llm.rate_limiter import AsyncRateLimiter, is_rate_limit_error


def test_is_rate_limit_error():
    assert is_rate_limit_error(Exception("429 Resource Exhausted"))
    assert is_rate_limit_error(Exception("Quota exceeded for quota metric"))
    assert not is_rate_limit_error(Exception("Invalid API key"))
    assert not is_rate_limit_error(ValueError("Bad arguments"))


@pytest.mark.asyncio
async def test_rate_limiter_pacing():
    # Allow 2 requests in 0.5s window with 0.1s minimum spacing
    limiter = AsyncRateLimiter(max_requests=2, window_seconds=0.5, min_interval=0.1)

    t0 = asyncio.get_event_loop().time()
    await limiter.acquire()
    await limiter.acquire()
    # Third request should be paced by the window
    await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - t0

    assert elapsed >= 0.3  # Paced cleanly


@pytest.mark.asyncio
async def test_exponential_backoff_retry():
    limiter = AsyncRateLimiter(max_requests=10, window_seconds=1.0, min_interval=0.01)

    attempts = 0
    on_rate_limit = AsyncMock()

    async def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception("429 Resource has been exhausted")
        return "success"

    result = await limiter.execute_with_retry(
        flaky_call,
        on_rate_limit=on_rate_limit,
        max_retries=3,
        base_delay=0.05,
    )

    assert result == "success"
    assert attempts == 3
    assert on_rate_limit.call_count >= 2
