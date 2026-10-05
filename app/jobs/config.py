"""Worker configuration loaded from system settings (never hardcoded)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jobs.retry import RetrySettings
from app.settings.service import SettingsService

KEY_MAX_JOBS = "worker.maximum_concurrent_jobs"
KEY_MAX_PROVIDER = "worker.maximum_provider_concurrency"
KEY_LEASE = "worker.lease_seconds"
KEY_HEARTBEAT = "worker.heartbeat_seconds"
KEY_POLL = "worker.poll_interval_seconds"
KEY_RETRY_ATTEMPTS = "worker.retry.max_attempts"
KEY_RETRY_INITIAL = "worker.retry.initial_delay_seconds"
KEY_RETRY_MAX = "worker.retry.max_delay_seconds"
KEY_RETRY_MULTIPLIER = "worker.retry.backoff_multiplier"
KEY_RETRY_JITTER = "worker.retry.jitter"
KEY_REPAIR_ENABLED = "worker.context_repair.enabled"
KEY_REPAIR_MIN_BATCH = "worker.context_repair.min_batch_size"
KEY_CREDITS_ENABLED = "billing.enabled"
KEY_CREDITS_PER_1K = "billing.credits_per_1000_tokens"
KEY_PROVIDER_MARKUP = "billing.provider_cost_markup"

_DEFAULTS: dict[str, Any] = {
    KEY_MAX_JOBS: 2,
    KEY_MAX_PROVIDER: 4,
    KEY_LEASE: 900,
    KEY_HEARTBEAT: 30,
    KEY_POLL: 5.0,
    KEY_RETRY_ATTEMPTS: 3,
    KEY_RETRY_INITIAL: 1.0,
    KEY_RETRY_MAX: 30.0,
    KEY_RETRY_MULTIPLIER: 2.0,
    KEY_RETRY_JITTER: 0.2,
    KEY_REPAIR_ENABLED: True,
    KEY_REPAIR_MIN_BATCH: 1,
    KEY_CREDITS_ENABLED: True,
    KEY_CREDITS_PER_1K: 1.0,
    KEY_PROVIDER_MARKUP: 0.0,
}


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    max_concurrent_jobs: int = 2
    max_provider_concurrency: int = 4
    lease_seconds: int = 900
    heartbeat_seconds: int = 30
    poll_interval_seconds: float = 5.0
    retry: RetrySettings = field(default_factory=RetrySettings)
    context_repair_enabled: bool = True
    context_repair_min_batch_size: int = 1
    credits_enabled: bool = True
    credits_per_1000_tokens: float = 1.0
    provider_cost_markup: float = 0.0


async def load_worker_settings(settings: SettingsService | None) -> WorkerSettings:
    async def value(key: str) -> Any:
        if settings is None:
            return _DEFAULTS[key]
        return await settings.get(key, _DEFAULTS[key])

    return WorkerSettings(
        max_concurrent_jobs=max(1, int(await value(KEY_MAX_JOBS))),
        max_provider_concurrency=max(1, int(await value(KEY_MAX_PROVIDER))),
        lease_seconds=max(30, int(await value(KEY_LEASE))),
        heartbeat_seconds=max(5, int(await value(KEY_HEARTBEAT))),
        poll_interval_seconds=max(0.5, float(await value(KEY_POLL))),
        retry=RetrySettings(
            max_attempts=max(1, int(await value(KEY_RETRY_ATTEMPTS))),
            initial_delay_seconds=float(await value(KEY_RETRY_INITIAL)),
            max_delay_seconds=float(await value(KEY_RETRY_MAX)),
            backoff_multiplier=float(await value(KEY_RETRY_MULTIPLIER)),
            jitter=float(await value(KEY_RETRY_JITTER)),
        ),
        context_repair_enabled=bool(await value(KEY_REPAIR_ENABLED)),
        context_repair_min_batch_size=max(1, int(await value(KEY_REPAIR_MIN_BATCH))),
        credits_enabled=bool(await value(KEY_CREDITS_ENABLED)),
        credits_per_1000_tokens=float(await value(KEY_CREDITS_PER_1K)),
        provider_cost_markup=float(await value(KEY_PROVIDER_MARKUP)),
    )
