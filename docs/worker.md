# Durable translation worker

The worker is a **separate process** from the API. FastAPI creates jobs; the
worker executes them. Book translation never runs inside a request or a
`BackgroundTasks` callback.

```
FastAPI  ──creates──►  translation_jobs  ──claims──►  Worker  ──►  TranslationEngine
```

```
uv run python -m worker.main                 # continuous
uv run python -m worker.main --once          # process at most one job
uv run python -m worker.main --job-id <id>   # run a specific job
uv run python -m worker.main --concurrency 4 # override max concurrent jobs
```

Requires `POCKETBASE_SERVICE_CREDENTIAL` (superuser token or `identity:password`)
so it can act across workspaces. It never needs the web frontend open.

## Components

| Module | Responsibility |
| --- | --- |
| `worker/main.py` | CLI, wiring, graceful shutdown signals. |
| `worker/runner.py` | Claim loop with bounded concurrency and stale recovery. |
| `worker/job_executor.py` | The resumable per-job pipeline. |
| `worker/heartbeat.py` | Lease refresh + stale-job recovery. |
| `app/jobs/store.py` | Persistent `JobStore` (claim/lease/segments/attempts/events). |
| `app/jobs/retry.py` | Configurable retry policy (backoff + jitter). |
| `app/jobs/config.py` | Worker settings loaded from system settings. |
| `app/providers/runtime.py` | Resolve connection + decrypted key → provider adapter. |

## Job lifecycle

`queued → preparing → parsing → segmenting → translating → finalizing →
completed` (with `failed`, `cancelling`, `cancelled`). Every transition is
explicit and recorded in `job_events`.

## Claiming & leases

A claim sets `worker_id`, `lease_id`, `lease_expires_at`, `last_heartbeat` and
moves the job to `preparing`. The lease is verified after claiming (best-effort
optimistic claim). `LeaseHeartbeat` refreshes it while the job runs. If the
worker dies, the lease expires and `recover_stale()` returns the job to
`queued` — without duplicating the source, segments, or book order.

```
# ponytail: best-effort optimistic claim; wrap in a PocketBase transaction /
# table lock when strict multi-worker claiming under contention is required.
```

## Concurrency

Bounded by configuration — never hardcoded:

- `worker.maximum_concurrent_jobs`
- `worker.maximum_provider_concurrency`

Jobs run as async tasks under a semaphore; provider calls are additionally
gated by a global semaphore. No Redis is required.

## Execution pipeline

```
prepare → parse → segment → persist → translate → finalize → export →
upload → complete
```

Each stage is idempotent enough to re-run after a crash:

- segments exist → parsing/segmenting is skipped;
- completed segments (validated + translated) are never retranslated;
- output is written to a deterministic storage key with a checksum.

## Segment execution

Each segment has its own persisted state: `pending`, `translating`, `failed`,
`skipped`, or `validated`. A batch returning is never assumed to mean every
segment succeeded — the engine validates and returns per-segment results.

## Retries & repair

Configured via `worker.retry.*` (attempts, initial delay, max delay, backoff
multiplier, jitter). Transient failures (`rate_limited`, `timeout`,
`provider_unavailable`, `unknown_provider_error`) are retried; permanent failures
(`authentication_error`, `invalid_request`, unsupported config) are not.

- **Context too large** → a repair strategy shrinks batch size and context
  (`worker.context_repair.*`) and retries the affected segments, rather than
  repeating the identical request.
- **Invalid structured response** → recorded as a failed attempt, optionally
  retried per policy, eventually marked failed. Random text is never extracted
  from a malformed response.

Every attempt increments `attempt_count` and appends a `translation_attempts`
record; previous attempts are never overwritten.

### Systemic provider failures

A provider rejecting the credential (`401`/`403`) is not retried per segment:
the worker stops on the first affected batch, fails the job with
`PROVIDER_AUTH_FAILED`, and asks the operator to update the connection key.
This avoids writing thousands of identical failed attempts.

### Upstream outages

A transport failure reaching PocketBase or storage raises `UpstreamError`. The
worker clears the lease and requeues the job with an `upstream_retries` counter,
so the next poll resumes from the persisted segments. Requeues are bounded at 20;
after that the job fails with the upstream error instead of looping forever.

## Cancellation

Cooperative: the API sets `cancellation_requested`. The worker observes it at
safe checkpoints, moves the job to `cancelling`, and finishes as `cancelled` —
never leaving a half-written output.

## Resume & partial retries

A resumed job preserves the original plan snapshot, skips validated/translated
segments, and translates both failed and never-attempted pending segments.
Completed work is never redone and translation memory is reused.

## Progress

Computed from segment state (`total`, `completed`, `failed`, `pending`,
`percentage`) — never from arbitrary timers.

## Idempotency

Source stored once; segments created once per job; completed segments skipped;
output uploaded to a stable key.

## Observability

Structured logs carry `job_id`, `document_id`, `segment_id`, provider, model,
attempt, duration, status and `error_code`. Full document contents and
credentials are never logged.
