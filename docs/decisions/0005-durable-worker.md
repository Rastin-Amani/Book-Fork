# ADR 0005 — Durable worker, leases, and no Redis

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Book translation is long-running and must survive browser closure, worker
restarts, and crashes, without corrupting credit accounting. The brief forbids
`BackgroundTasks` for book translation and forbids introducing Redis solely to
solve queueing.

## Decision

- **Dedicated worker process.** FastAPI creates `translation_jobs`; a separate
  worker claims and executes them. No `BackgroundTasks` for translation.
- **The job records are the queue.** Claiming uses persistent lease fields
  (`worker_id`, `lease_id`, `lease_expires_at`, `last_heartbeat`); stale leases
  are recovered back to `queued`. No Redis.
- **Bounded async concurrency**, configured from system settings
  (`worker.maximum_concurrent_jobs`, `worker.maximum_provider_concurrency`).
- **Explicit, evented lifecycle** with resumable, idempotent stages and
  cooperative cancellation.
- **Configurable retry + repair**: exponential backoff with jitter, plus
  context-size repair and invalid-response retries. Attempts are appended to
  `translation_attempts`, never overwritten.

## Consequences

- Recovery after a crash is a matter of lease expiry + idempotent stage re-runs;
  credits are safe because reservation/settlement are reference-guarded.
- Multiple workers are possible later; the only known limitation is the
  best-effort optimistic claim, which should be wrapped in a database
  transaction/table lock for strict multi-worker contention.
- Operational state lives entirely in PocketBase, so there is no extra
  infrastructure to run.
