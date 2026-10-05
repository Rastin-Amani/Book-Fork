"""Readiness checks for runtime dependencies.

Kept out of the HTTP layer so both the API and operational tooling can reuse it.
Checks are cheap and must not touch expensive code paths.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.logging import get_logger
from app.repositories.pocketbase import PocketBaseClient
from app.storage.base import Storage

logger = get_logger(__name__)

_CHECK_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checks: list[CheckResult] = field(default_factory=list)


class HealthService:
    """Aggregates dependency readiness for ``/health/ready``."""

    def __init__(self, *, pocketbase: PocketBaseClient, storage: Storage) -> None:
        self._pocketbase = pocketbase
        self._storage = storage

    async def readiness(self) -> ReadinessReport:
        results = await asyncio.gather(
            self._check_pocketbase(), self._check_storage(), return_exceptions=False
        )
        return ReadinessReport(ready=all(r.ok for r in results), checks=list(results))

    async def _check_pocketbase(self) -> CheckResult:
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                ok = await self._pocketbase.health()
        except Exception as exc:
            logger.warning("readiness_pocketbase_error", error=type(exc).__name__)
            return CheckResult("pocketbase", False, "unreachable")
        return CheckResult("pocketbase", ok, None if ok else "unhealthy")

    async def _check_storage(self) -> CheckResult:
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                await self._storage.exists("health/sentinel")
        except Exception as exc:
            logger.warning("readiness_storage_error", error=type(exc).__name__)
            return CheckResult("storage", False, "unavailable")
        return CheckResult("storage", True)
