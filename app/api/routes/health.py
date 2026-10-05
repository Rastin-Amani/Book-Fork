"""Health, readiness, worker-liveness and metrics endpoints.

``/health`` proves the process is alive. ``/health/ready`` validates runtime
dependencies (and is safe to poll). ``/health/worker`` proves a translation worker
is alive. ``/metrics`` exposes lightweight Prometheus text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.dependencies import CtxDep
from app.observability.metrics import metrics
from app.repositories.workers import WorkerRepository

router = APIRouter(tags=["health"])

# A worker that has not heartbeat within this window is considered dead. The
# worker heartbeats far more often; this is a liveness ceiling, not policy.
_WORKER_STALE_SECONDS = 180


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(ctx: CtxDep) -> JSONResponse:
    """Readiness: required dependencies are reachable."""
    report = await ctx.health.readiness()
    body = {
        "ready": report.ready,
        "checks": [
            {"name": c.name, "ok": c.ok, **({"detail": c.detail} if c.detail else {})}
            for c in report.checks
        ],
    }
    return JSONResponse(body, status_code=200 if report.ready else 503)


@router.get("/health/worker")
async def worker_health(ctx: CtxDep) -> JSONResponse:
    """Worker liveness: is a translation worker currently heartbeating?"""
    token = await ctx.ensure_service_token()
    if token is None:
        return JSONResponse(
            {"alive": False, "reason": "service credential not configured"}, status_code=503
        )
    workers = await WorkerRepository(ctx.pocketbase, token=token).list(sort="-last_heartbeat")
    cutoff = datetime.now(UTC) - timedelta(seconds=_WORKER_STALE_SECONDS)
    alive: list[object] = []
    for worker in workers:
        heartbeat = _parse(worker.last_heartbeat) if worker.last_heartbeat else None
        if heartbeat is not None and heartbeat >= cutoff:
            alive.append(worker)
    return JSONResponse(
        {
            "alive": bool(alive),
            "workers": [
                {
                    "worker_id": worker.worker_id,
                    "status": worker.status,
                    "current_jobs": worker.current_jobs,
                    "last_heartbeat": worker.last_heartbeat,
                }
                for worker in workers
            ],
        },
        status_code=200 if alive else 503,
    )


@router.get("/metrics")
async def prometheus() -> PlainTextResponse:
    """Lightweight metrics exposition (per-process)."""
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
