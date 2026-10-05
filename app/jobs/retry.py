"""Retry policy for the worker.

Configured entirely from settings (attempts, backoff, jitter). Retries transient
failures only; permanent failures (auth, invalid request, unsupported config) are
not retried endlessly.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrySettings:
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    jitter: float = 0.2


class RetryService:
    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        random_source: Callable[[], float] | None = None,
    ) -> None:
        self._sleep = sleep or asyncio.sleep
        self._random = random_source or random.random

    def should_retry(self, settings: RetrySettings, *, attempt: int, retryable: bool) -> bool:
        return retryable and attempt < settings.max_attempts

    def delay(self, settings: RetrySettings, *, attempt: int) -> float:
        base = settings.initial_delay_seconds * (settings.backoff_multiplier ** max(0, attempt - 1))
        base = min(base, settings.max_delay_seconds)
        spread = max(0.0, settings.jitter)
        factor = 1.0 + (self._random() * 2.0 - 1.0) * spread
        return max(0.0, base * factor)

    async def wait(self, settings: RetrySettings, *, attempt: int) -> None:
        await self._sleep(self.delay(settings, attempt=attempt))
