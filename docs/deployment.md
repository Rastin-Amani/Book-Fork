# Deployment

Book Fork runs as three production services behind a reverse proxy: **PocketBase**,
**book-fork-api** (FastAPI + templates + static assets) and **book-fork-worker** (the
durable translation worker). The API never starts translation workers inside the
web process. Object storage is local by default and S3-compatible optionally.

## Containers

`Dockerfile` is multi-stage: stage 1 builds frontend assets (Tailwind + daisyUI +
vendored HTMX/Alpine) with Node, stage 2 is a Python 3.14 slim runtime that copies
only the built assets. **Node is not present in the runtime image.**

`compose.yaml` wires `pocketbase`, `app`, `worker`, and an optional `minio`
(profile `s3`). The `app` service has a readiness health check against
`/health/ready`.

The image's `CMD` is `docker-entrypoint.sh`: it runs the web process plus
`WORKERS` supervised worker processes (default `1`) in one container, so a
Dockerfile deploy (Dokploy, `docker run`, a rebuilt image) always starts a
worker pool — no separate worker container to forget. Each slot gets a stable
`WORKER_ID`, `SIGTERM`/`SIGINT` is forwarded so in-flight jobs are requeued
gracefully, and a crashed slot is restarted in place. Set `WORKERS=0` to run
the web only, or override the command with `python -m worker.main` for a
worker-only container. `compose.yaml` keeps its dedicated `worker` service and
sets `WORKERS=0` on `app`, so the two do not overlap.

## Book outputs (PDF / EPUB)

The worker produces a print-ready PDF (PyMuPDF, pure Python) and an EPUB
(`DOCUMENT_OUTPUT_FORMATS`). Fonts are bundled with the application, so no
system font packages are required. **WeasyPrint** is an alternative PDF backend
and needs the `pdf` extra plus pango/cairo/gdk-pixbuf; the default `pymupdf`
backend needs none.

No configuration change is required to start producing PDF and EPUB.

## Health checks

| Endpoint | Meaning |
|---|---|
| `/health` | process alive (no dependencies touched) |
| `/health/ready` | PocketBase + storage reachable; 503 otherwise |
| `/health/worker` | at least one worker heartbeating within the liveness window; 503 otherwise |
| `/metrics` | lightweight Prometheus text (per-process) |

The worker registers itself in the `workers` collection and refreshes its
heartbeat each poll; `/health/worker` distinguishes "worker process alive" from
"web process alive".

## Environment

Only infrastructure and secrets belong in the environment (see `.env.example` and
`docs/configuration.md`). Required secrets: `APP_SECRET_KEY`, `ENCRYPTION_KEY`,
`WORKER_INTERNAL_TOKEN`, and `POCKETBASE_SERVICE_CREDENTIAL` for the worker and
admin. Business configuration (languages, providers, models, prompts, pricing,
limits, retention, rate-limit-adjacent thresholds) lives in PocketBase.

## Reverse proxy & HTTPS

- `APP_BASE_URL` / `ROOT_PATH` describe the external URL and optional sub-path.
- `TRUSTED_HOSTS` restricts accepted `Host` headers.
- `COOKIE_SECURE` must be true in production (enforced by settings validation).
- `FORWARDED_ALLOW_IPS` lists proxies whose `X-Forwarded-*` headers are trusted;
  uvicorn reads it and applies proxy headers. Do not trust forwarded headers from
  the public internet.
- `CORS_ORIGINS` is empty by default; the app is same-origin.

## Run order

```bash
# 1. PocketBase + schema + seeds
docker compose up -d pocketbase
uv run python scripts/push_schema.py ...   # or run pb_migrations on the server
uv run python scripts/seed.py

# 2. API and worker
docker compose up -d app worker
```

## Backups

Back up **all** of the following — database-only backups lose uploaded files:

- PocketBase data directory (`pb_data`) and the `pb_migrations` definitions.
- Seed/configuration (`seeds/`) as source of truth for defaults.
- Object storage (`STORAGE_LOCAL_ROOT`, or the S3 bucket/MinIO volume).

Document backups should be consistent with the database (point-in-time is ideal);
otherwise a restored database may reference objects a later snapshot removed.

## Data retention

Retention is configuration, never a Python constant. `scripts/retention.py`
(configured by `retention.*` settings) removes old sources, outputs, failed jobs,
attempts, job events and temp files. An unset/zero window means "keep". Schedule
it (cron/systemd timer/worker host). Records referenced by an active job are never
removed. See `docs/configuration.md` for the keys.

## Acceptance walkthrough

A fresh developer can: clone → copy `.env.example` to `.env` → start PocketBase →
run migrations + seeds → start the API and worker → open the browser → register →
upload an EPUB/PDF → pick arbitrary source/target languages → choose Book Fork AI or
their own provider → estimate → start → watch progress → recover from a worker
restart → retry failures → download the translated document — with no source edits.
