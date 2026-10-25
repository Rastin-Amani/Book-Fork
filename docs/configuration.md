# Configuration

Book Fork separates **infrastructure/secrets** (environment) from **business
behaviour** (PocketBase data).

## Environment variables

Copy `.env.example` to `.env` and fill in real values. `.env` is git-ignored.
Generate secrets with:

```bash
uv run python scripts/generate_secrets.py
```

### Application

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | no | `development` | `development` \| `test` \| `production`. |
| `APP_NAME` | no | `Book Fork` | Display name. |
| `APP_BASE_URL` | no | `http://localhost:8000` | Canonical URL. |
| `APP_SECRET_KEY` | **yes** | — | Signs CSRF tokens. |
| `DEBUG` | no | `false` | |
| `LOG_LEVEL` | no | `INFO` | |
| `LOG_JSON` | no | `false` | JSON logs for production. |

### PocketBase

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `POCKETBASE_URL` | no | `http://127.0.0.1:8090` | |
| `POCKETBASE_SERVICE_CREDENTIAL` | no | — | For trusted server-side admin ops. |
| `POCKETBASE_USERS_COLLECTION` | no | `users` | Auth collection name. |

### Sessions / cookies

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `SESSION_COOKIE_NAME` | no | `book_fork_session` | |
| `SESSION_MAX_AGE_SECONDS` | no | `1209600` (14 days) | |
| `COOKIE_DOMAIN` | no | — | |
| `COOKIE_SECURE` | no | derived | Defaults to `true` when `APP_ENV=production`. |
| `COOKIE_SAMESITE` | no | `lax` | `lax` \| `strict` \| `none`. |

### Secrets

| Variable | Required | Notes |
| --- | --- | --- |
| `ENCRYPTION_KEY` | **yes** | Encrypts provider keys and the session cookie. |
| `WORKER_INTERNAL_TOKEN` | **yes** | Authenticates API→worker calls. |

### Storage

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `STORAGE_BACKEND` | no | `local` | `local` \| `s3`. |
| `STORAGE_LOCAL_ROOT` | no | `var/storage` | Local backend root. |
| `S3_ENDPOINT` | s3 only | — | |
| `S3_BUCKET` | s3 only | — | Required when `STORAGE_BACKEND=s3`. |
| `S3_ACCESS_KEY` | s3 only | — | Required when `STORAGE_BACKEND=s3`. |
| `S3_SECRET_KEY` | s3 only | — | Required when `STORAGE_BACKEND=s3`. |
| `S3_REGION` | no | — | |

### Document processing (safety ceilings, not product limits)

These are infrastructure safety ceilings for parsing untrusted files. The
user-facing file-size limit is the `upload.maximum_file_size` system setting.

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DOCUMENT_TEMP_ROOT` | no | `var/tmp` | Managed temp directory root. |
| `DOCUMENT_MAX_UNCOMPRESSED_BYTES` | no | `524288000` | Total uncompressed archive ceiling. |
| `DOCUMENT_MAX_ARCHIVE_ENTRIES` | no | `5000` | Max ZIP entries (ZIP-bomb guard). |
| `DOCUMENT_MAX_COMPRESSION_RATIO` | no | `200` | Max per-entry compression ratio. |
| `DOCUMENT_MAX_TEXT_BLOCKS` | no | `200000` | Max extracted text blocks. |
| `DOCUMENT_MAX_PDF_PAGES` | no | `5000` | Max PDF pages. |
| `DOCUMENT_RENDER_BACKEND` | no | `pymupdf` | `pymupdf` \| `html` \| `weasyprint`. |
| `DOCUMENT_OUTPUT_FORMATS` | no | `epub,pdf` | Formats produced per finished job. |
| `DOCUMENT_BOOK_PAGE_SIZE` | no | `a5` | Trim size: `a4` \| `a5` \| `b5` \| `letter` \| `a6`. |
| `DOCUMENT_FONT_DIR` | no | — | Optional extra `Family-Regular.ttf` / `Family-Bold.ttf`. |
| `OCR_PROVIDER` | no | `none` | `none` (future: tesseract/paddleocr/cloud). |

### Web / transport security

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `MAX_REQUEST_BYTES` | no | `104857600` | Transport ceiling, **not** the product file-size limit. |
| `TRUSTED_HOSTS` | no | `["localhost","127.0.0.1"]` | JSON array. |
| `CORS_ORIGINS` | no | `[]` | JSON array. |
| `ENABLE_DOCS` | no | `true` | Disabled in production regardless. |
| `SECURITY_HEADERS_ENABLED` | no | `true` | CSP + hardening headers. |
| `CONTENT_SECURITY_POLICY` | no | built-in | Override the HTMX/Alpine-compatible default. |
| `FORWARDED_ALLOW_IPS` | no | `127.0.0.1` | Proxies trusted for `X-Forwarded-*`. |
| `ROOT_PATH` | no | — | When mounted under a sub-path. |
| `RATE_LIMIT_ENABLED` | no | `true` | Master switch. |
| `RATE_LIMIT_AUTH_PER_MINUTE` | no | `30` | Per client IP. |
| `RATE_LIMIT_SIGNUP_PER_MINUTE` | no | `10` | |
| `RATE_LIMIT_PASSWORD_RESET_PER_MINUTE` | no | `10` | |
| `RATE_LIMIT_UPLOAD_PER_MINUTE` | no | `20` | Per user/IP. |
| `RATE_LIMIT_PROVIDER_TEST_PER_MINUTE` | no | `20` | |
| `RATE_LIMIT_TRANSLATION_PER_MINUTE` | no | `30` | |
| `RATE_LIMIT_RETRY_PER_MINUTE` | no | `30` | |

## System settings (business behaviour)

Seeded into `system_settings` by `scripts/seed.py`. Admin-editable at
`/admin/system-settings`. Keys added in Phase 8:

| Key | Meaning |
| --- | --- |
| `limits.uploads_per_day` | Max uploads per workspace/day (0 = unlimited). |
| `limits.jobs_per_day` | Max jobs per workspace/day (0 = unlimited). |
| `limits.max_concurrent_jobs_per_user` | Max active jobs per workspace (0 = unlimited). |
| `limits.retries_per_job` | Max manual retries per job (0 = unlimited). |
| `retention.source_documents_days` | Delete source documents after N days (0 = keep). |
| `retention.output_documents_days` | Delete translated outputs after N days (0 = keep). |
| `retention.failed_jobs_days` | Delete failed/cancelled jobs after N days (0 = keep). |
| `retention.translation_attempts_days` | Delete attempts after N days (0 = keep). |
| `retention.job_events_days` | Delete job events after N days (0 = keep). |
| `retention.temp_files_hours` | Delete temp files after N hours (0 = keep). |
| `admin.emails` | JSON list of admin email addresses. |

### Full seeded setting groups

The authoritative list with defaults, types and descriptions is
[`../seeds/system_settings.json`](../seeds/system_settings.json). Grouped by
prefix:

- **`upload.*`** — `maximum_file_size` (default 104857600 bytes),
  `allowed_extensions`.
- **`jobs.*`** — `maximum_concurrent_jobs`, `default_lease_seconds`,
  `heartbeat_seconds`, `max_attempts`.
- **`worker.*`** — `maximum_concurrent_jobs`, `maximum_provider_concurrency`,
  `lease_seconds`, `heartbeat_seconds`, `poll_interval_seconds`,
  `retry.*` (max attempts, initial/max delay, backoff, jitter),
  `context_repair.enabled`, `context_repair.min_batch_size`.
- **`translation.*`** — `default_batch_size`, `default_context_size`,
  `max_output_tokens`, `retry.*`, `context.*` (strategy, max previous segments,
  max context tokens, max glossary terms), `fallback.strategy`,
  `default_prompt_template_slug`, `default_profile_name`,
  `detection_min_confidence`.
- **`billing.*`** — `book_price_usd`, `pages_per_block`, `words_per_page`,
  `default_currency` (non-editable).
- **`providers.*`** — `raw_response_retention` (default `false`).
- **`storage.*`** — `retention_days`.
- **`limits.*`** and **`retention.*`** — as above.
- **`admin.*`** — `emails`.

> **Known inconsistency (verified).** `upload.allowed_extensions` is seeded as
> `["epub","pdf","txt","docx"]`, but the ingestion path sniffs content and
> accepts **EPUB and PDF only** (`app/documents/ingest.py`). The setting is not
> currently consulted by the upload path. Treat EPUB/PDF as the supported set
> until that is reconciled.

## What must NOT be environment variables

Business/translation configuration belongs in PocketBase records and job
snapshots, never in the environment:

- source/target languages, language pairs, direction/RTL lists;
- providers, base URLs, API keys (user-provided keys are stored **encrypted**),
  models, capabilities;
- temperature, token limits, chunk/batch sizes, retry counts/delays;
- translation/system prompts, glossary and translation-memory rules;
- per-book pricing, provider costs, quality profiles;
- document file-size/page limits, retention, concurrency.

The only exception is infrastructure secrets (above), which must not live in the
database.
