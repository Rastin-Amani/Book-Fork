# Book Fork — Operations Runbook

Day-two operations for a self-hosted Book Fork: running the services, watching
health, scaling, maintenance, backups, upgrades and incident response.

> **Verification status.** Health thresholds, worker behaviour and settings were
> checked in `app/api/routes/health.py`, `app/observability/metrics.py`,
> `worker/heartbeat.py`, `worker/runner.py`, `app/jobs/config.py`,
> `scripts/retention.py` and `deploy/*.service.tpl`. Deployment topology is in
> [Deployment](deployment.md).

---

## 1. Service topology

Three processes (plus storage) make up a deployment:

| Service | Process | Role |
| --- | --- | --- |
| PocketBase | `pocketbase serve` | Identity, data, schema, job store. |
| API / web | `uvicorn app.main:app` | Pages, forms, HTMX fragments, health. |
| Worker | `python -m worker.main` | Claims and executes translation jobs. |
| Storage | local filesystem or S3 | Source documents and outputs. |

The API **never** runs translation in-process. The worker is independent and
claims jobs from PocketBase with per-job leases, so it can be restarted or
scaled without touching the web tier.

---

## 2. Running the services

### Containers

```bash
docker compose up -d pocketbase
docker compose up -d app worker
```

`compose.yaml` provides `pocketbase`, `app`, `worker` and an optional `minio`
(profile `s3`). The `app` service has a health check against `/health/ready`
every 30 s (10 s timeout, 3 retries, 20 s start period).

### systemd (bare host)

```bash
make install-web-service      # installs + enables book-fork-web.service
make install-worker-service   # installs + enables book-fork-worker.service
journalctl -u book-fork-web -f
journalctl -u book-fork-worker -f
```

Both units run as the invoking user from the project root, restart on failure
(`Restart=always`, 5 s), and load `.env` from the working directory.

### Worker CLI

```bash
uv run python -m worker.main                  # continuous
uv run python -m worker.main --once           # process one job then exit
uv run python -m worker.main --job-id <id>    # run a specific job
uv run python -m worker.main --concurrency 4  # override max concurrent jobs
```

The worker **refuses to start** without `POCKETBASE_SERVICE_CREDENTIAL`.

---

## 3. Health and monitoring

| Endpoint | Meaning | Threshold |
| --- | --- | --- |
| `GET /health` | Process alive (touches no dependencies). | Always 200 when up. |
| `GET /health/ready` | PocketBase + storage reachable. | 200 ready; 503 not; each check 3 s timeout. |
| `GET /health/worker` | A worker heartbeated recently. | 200 if any heartbeat within **180 s**, else 503. |
| `GET /metrics` | Prometheus text (per process). | Scrape and aggregate across replicas yourself. |

Worker liveness is how you tell “the web process is up” from “translations can
actually make progress”. Alert on `/health/worker` returning 503.

`/health/worker` returns 503 with `"reason": "service credential not configured"`
when the API has no `POCKETBASE_SERVICE_CREDENTIAL`.

### Metrics

Lightweight, in-process counters/gauges (no external dependency). They are
per-process; sum across replicas at scrape time. `/admin/metrics` shows the same
snapshot in the admin UI.

### Logs

Structured logs (structlog). `LOG_JSON=true` for production. Request ids are
minted server-side and echoed; sensitive keys are redacted; document bodies,
prompts and credentials are never logged. Worker logs carry `job_id`,
`document_id`, `segment_id`, provider, model, attempt, duration, status and
`error_code`.

---

## 4. Tuning

Business knobs live in **system settings** (admin →
`/admin/system-settings`), not the environment. Worker knobs are read at worker
startup via `app/jobs/config.py`:

| Setting | Default | Effect |
| --- | --- | --- |
| `worker.maximum_concurrent_jobs` | 2 | Jobs processed in parallel per worker. |
| `worker.maximum_provider_concurrency` | 4 | Concurrent provider requests (global). |
| `worker.poll_interval_seconds` | 5.0 | Queue poll interval. |
| `worker.lease_seconds` | 900 | Job lease before it becomes reclaimable. |
| `worker.heartbeat_seconds` | 30 | Lease refresh interval. |
| `worker.retry.*` | 3 attempts, 1 s→30 s, ×2, 0.2 jitter | Segment retry policy. |
| `worker.context_repair.enabled` | true | Shrink context/batch on `context_too_large`. |
| `billing.enabled` | true | Whether credit reservation/settlement runs. |
| `billing.credits_per_1000_tokens` | 1.0 | Credit price per 1k tokens. |
| `billing.provider_cost_markup` | 0.0 | Credits per unit of provider cost. |

---

## 5. Scaling

- **Web replicas:** stateless; scale behind the proxy. The per-process rate
  limiter and metrics are **not** shared across replicas (documented
  limitation) — use sticky limits at the proxy for strict enforcement.
- **Workers:** safe to run several. Each claims with a unique `worker_id` and a
  lease; a stale lease is recovered and requeued without duplicating segments or
  credits. Bound total provider load with `worker.maximum_provider_concurrency`
  per worker.
- **PocketBase:** the single data authority; scale it per PocketBase's own
  guidance.
- **Storage:** S3-compatible backends allow the API and workers to scale
  horizontally without shared disk.

---

## 6. Data retention

Retention is configuration, never code. `scripts/retention.py` reads
`retention.*` settings; a **0 or unset window means “keep”**. It deletes only
eligible records and skips anything referenced by an active job.

| Setting | Deletes |
| --- | --- |
| `retention.source_documents_days` | Source documents (and canonical JSON) older than N days. |
| `retention.output_documents_days` | Translated outputs older than N days. |
| `retention.failed_jobs_days` | Failed/cancelled jobs (with segments/attempts/events/output). |
| `retention.translation_attempts_days` | Translation attempts older than N days. |
| `retention.job_events_days` | Job events older than N days. |
| `retention.temp_files_hours` | Stray temp files older than N hours. |

Schedule it (cron, systemd timer, or a scheduled container):

```bash
uv run python scripts/retention.py
```

It requires `POCKETBASE_SERVICE_CREDENTIAL` and logs a summary
(`documents_deleted`, `jobs_deleted`, `attempts_deleted`, `events_deleted`,
`temp_files_deleted`).

---

## 7. Backups and restore

Back up **all three** together — a database-only backup loses uploaded files:

1. PocketBase data directory (`pb_data`) and `pb_migrations/`.
2. Object storage (`STORAGE_LOCAL_ROOT`, or the S3 bucket / MinIO volume).
3. `seeds/` as the source of truth for defaults.

Prefer point-in-time consistency between the database and storage; otherwise a
restore may reference objects a later snapshot removed.

**Restore order:** PocketBase data and schema (or `scripts/push_schema.py` +
`scripts/seed.py`) → object storage → start API → start worker. Then verify
`/health/ready` and `/health/worker`.

---

## 8. Upgrades

1. Back up (above).
2. Pull the new code.
3. `uv sync` and `npm ci && npm run build` (or rebuild the container image).
4. Apply PocketBase migrations (run PocketBase against `pb_migrations/`) or push
   schema to an instance that cannot migrate.
5. Restart API, then worker. Workers drain in-flight jobs on `SIGTERM`/`SIGINT`
   and mark themselves `stopped`.
6. Verify health and run a small translation end to end.

Jobs are resumable and carry a plan snapshot, so an upgrade mid-job does not
change a job's resolved configuration.

---

## 9. Incident response

### Worker down

- **Detect:** `/health/worker` 503; `/admin/workers` shows stale heartbeats.
- **Impact:** jobs remain `queued`; nothing is lost.
- **Act:** restart the worker (systemd/compose/CLI). It runs `recover_stale()`
  on start and requeues expired leases.

### Worker crash mid-job

- The lease expires after `worker.lease_seconds`; `recover_stale()` requeues the
  job. Already-validated segments are skipped, the credit reservation is
  reference-guarded (`job:<id>:reserve`), and output goes to a deterministic key
  — so recovery does not double-charge or duplicate work.

### PocketBase unavailable

- `/health/ready` returns 503 with `pocketbase: unreachable`. Logins and data
  operations fail; the identity service being down is surfaced as an upstream
  error, not a login failure.

### Provider outage / rate limits

- Jobs fail with `PROVIDER_*` codes and are retried per policy. Switch a
  connection/model or retry later. Reducing
  `worker.maximum_provider_concurrency` lowers pressure.

### Disk / storage pressure

- Enable `retention.temp_files_hours` to sweep temp files, and a source/output
  window if appropriate. Ensure `document_temp_root` is on a volume with
  headroom; books are processed in managed temp directories that clean up.

---

## 10. Common maintenance commands

```bash
make seed                    # idempotent reference data
uv run python scripts/push_schema.py ...   # sync schema to a remote PocketBase
uv run python scripts/retention.py         # retention sweep
make check                   # lint + typecheck + tests
```
