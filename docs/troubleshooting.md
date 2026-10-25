# Book Fork — Troubleshooting

Organised by symptom. Each entry gives likely causes, how to verify, and the
resolution. Steps reference routes and commands verified in this repository.

> **Design principle.** Book Fork prefers refusing a request over producing a
> silently wrong result. Many “failures” below are deliberate refusals.

---

## A. Jobs

### A job stays `queued` forever

**Causes:** no worker process is running, the worker lacks a service credential,
or the worker cannot reach PocketBase.

**Verify:**
1. `GET /health/worker` — 200 means a worker heartbeated within the last 180 s;
   503 means none did.
2. Check the body: `"reason": "service credential not configured"` means the API
   has no `POCKETBASE_SERVICE_CREDENTIAL` and cannot even read worker records.
3. Look at `/admin/workers` for last heartbeats.
4. In the worker log: `POCKETBASE_SERVICE_CREDENTIAL is required to run the worker.`
   means the worker refused to start.

**Resolve:** start the worker (`uv run python -m worker.main` or the worker
service/container) with `POCKETBASE_SERVICE_CREDENTIAL` set. Jobs resume
automatically; no need to recreate them.

### A job is `failed`

**Verify:** open the job page — the status panel shows `job.error_message`. Check
`/admin/failed-jobs` and `/admin/job-events` for the machine-readable
`error_code`.

**Interpret the code:**

| Code | Likely cause | Resolution |
| --- | --- | --- |
| `PROVIDER_AUTH_FAILED` | Wrong/expired API key for an own-API connection. | Re-check the key; use **Test** on the provider. |
| `PROVIDER_RATE_LIMITED` | Provider throttling. | Wait; lower `worker.maximum_provider_concurrency`; retry. |
| `PROVIDER_TIMEOUT` | Slow provider. | Retry; consider a different model/connection. |
| `PROVIDER_UNAVAILABLE` | Provider outage or endpoint unreachable. | Verify endpoint reachability; retry. |
| `MODEL_UNSUPPORTED` | No configured model capability for the pair. | Add a `model-capabilities` record for the pair (admin). |
| `TRANSLATION_VALIDATION_FAILED` | Response missing segments or failing glossary/placeholder checks. | Retry; inspect attempts; check the prompt version. |
| `OUTPUT_GENERATION_FAILED` | Book render failed. | Check worker logs; verify `DOCUMENT_OUTPUT_FORMATS` and font dir. |
| `DOCUMENT_*` | Bad or oversized source. | Re-upload a valid EPUB/PDF within the size limit. |

**Resolve:** when the status is `failed`, use **Retry failed** on the job page.
This retranslates only failed segments and preserves the original plan snapshot.

### Progress is stuck at a percentage

Progress comes from segment state (`completed/total`), not a timer. A stall
usually means provider calls are slow or the lease is being refreshed while the
worker waits. Check `/admin/workers` and worker logs. If the worker died, the
lease expires and `recover_stale()` requeues the job.

### A completed job has no output / download 404s

**Causes:** output generation failed, retention removed it, or the format was
not produced.

**Verify:** inspect the job's `metadata.outputs` (job page buttons) and
`output_storage_key`. Check `/admin/translation-jobs`. If retention windows are
set, they may have deleted the output — see §F.

---

## B. Translation quality and behaviour

### The glossary has no effect

**Cause (known limitation):** the UI does not yet expose attaching a glossary to
a translation job or profile. Terms are stored, and the engine reads
`profile_snapshot.glossary_ids`, but nothing in the current user flow sets that
list.

**Verify:** inspect a job snapshot (`/admin/translation-jobs`) for
`profile_snapshot.glossary_ids`.

**Status:** follow-up work, not a misconfiguration.

### Translation memory is never reused

**Causes:** no entries, entries are not **approved**, or the language pair does
not match exactly.

**Verify:** `/app/translation-memory` shows entries and their **Approved** flag.
Memory reuse requires `approved = true`; newly stored pairs are **not**
auto-approved.

**Resolve:** approve entries in the admin area
(`/admin/translation-memory`). Memory is always scoped to the exact pair.

### Language auto-detect refuses

**Symptom:** *“Could not detect the source language; choose one explicitly.”*

**Cause:** the detector could not determine a language from the document sample
(or confidence too low).

**Resolve:** pick the source language explicitly in the new-translation form.

### A PDF reports `ocr_required`

Pages with no extractable text are flagged rather than forced through OCR
(`OCR_PROVIDER=none` by default). Configure an OCR provider when one is
available; otherwise translate only text-based documents.

---

## C. Uploads and documents

### “Only EPUB and PDF documents are supported.”

Ingestion sniffs the content and accepts **EPUB and PDF only**. The
`upload.allowed_extensions` system setting currently lists `txt` and `docx`, but
those are **not** accepted by the ingestion path — treat EPUB/PDF as the
supported set.

### Upload rejected as too large

Two independent ceilings apply:

- `MAX_REQUEST_BYTES` — the transport safety ceiling.
- `upload.maximum_file_size` — the product limit (default 100 MiB).

Whichever is lower wins. Raise the appropriate setting if the limit is wrong for
your deployment.

### “The document could not be read.” / corrupted

The archive/text could not be parsed safely. Re-export the EPUB/PDF; avoid files
with broken archives or symlinked ZIP members.

---

## D. Accounts and sessions

### “Sign-in is not configured yet.”

**Cause:** PocketBase reports OAuth2 disabled, or neither Google nor GitHub
provider has both a client id and secret. This is an operator state, not an
outage.

**Resolve:** set `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` and/or
`GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`, then run:

```bash
uv run python scripts/configure_auth.py
```

Alternatively paste the credentials in PocketBase → Collections → `users` →
Options → OAuth2. Password/OTP/MFA sign-in is intentionally disabled.

### “Could not reach the sign-in service.”

PocketBase is unreachable or returned a 5xx while the login page asked for
`auth-methods`, or while the code exchange ran. Verify it with
`GET /health/ready` and check PocketBase logs.

### Provider says “redirect_uri_mismatch”

The callback registered at Google/GitHub does not match the URL the browser
used. Register exactly:

```
<APP_BASE_URL>/auth/oauth2/callback
```

(including scheme and port). The app builds the callback from the request origin,
so opening the app on `localhost:8000` requires that exact URL to be registered
for local development too.

### “That sign-in link expired. Please try again.”

The signed `oauth_state` cookie is missing, older than 10 minutes, or belongs to
another browser tab/domain. Start again from `/login`. A `state` error also
appears when a callback URL is opened without first loading the login page.

### Session loops back to login

**Causes:** `ENCRYPTION_KEY` changed (existing cookies can no longer be
decrypted), the cookie is `Secure` but you are on plain HTTP, or the cookie
domain is wrong.

**Verify:** check `APP_ENV`, `COOKIE_SECURE`, `COOKIE_DOMAIN` and whether the
browser stored `book_fork_session`. `Secure` is forced true in production.

**Resolve:** serve over HTTPS in production; keep `ENCRYPTION_KEY` stable; clear
the stale cookie and log in again.

### 403 *“Invalid or missing CSRF token.”*

The CSRF cookie/header pair is stale — usually a page left open across a restart
or a key change. Reload the page and try again.

### 429 *“Too many requests.”*

A rate limit was hit. Limits are per client IP (auth) or per user (uploads,
translations, provider tests, retries). Thresholds are environment configuration
(`RATE_LIMIT_*`); business limits use `limits.*` system settings.

---

## E. Admin access

### 403 *“Administrator access required.”*

Your signed-in email is not in the `admin.emails` system setting. Add it (via
PocketBase or the seed) and sign in again.

### Admin pages show a configuration error

`POCKETBASE_SERVICE_CREDENTIAL` is not set, so admin queries cannot use the
superuser token. Set it to a superuser token or `identity:password`.

### Admin area can’t be reached at all

The admin area lives at `/admin` (not a separate service). Ensure you are signed
in and that the app is not mounted under an unexpected `ROOT_PATH`.

---

## F. Operations

### `/health/ready` returns 503

`checks` names the failing dependency. `pocketbase: unreachable` or
`storage: unavailable` point at the cause. Each check has a 3-second timeout.

### Data disappeared

Check the `retention.*` settings. A non-zero window deletes sources, outputs,
failed jobs, attempts, events and temp files older than the window; `0` keeps
them. Retention also refuses to delete records referenced by an active job.
Restore from backups if needed (see [Operations](operations.md)).

### `/metrics` disagrees between instances

Metrics are per-process, not aggregated. Sum across replicas at scrape time.

### PDF/EPUB output uses the wrong fonts or misses glyphs

Bundled fonts cover Persian/Arabic-script targets (Vazirmatn) and Latin/Greek/
Cyrillic (Crimson Text). Other scripts fall back to the bundled default unless
you place `Family-Regular.ttf` / `Family-Bold.ttf` in `DOCUMENT_FONT_DIR`.

### WeasyPrint backend fails

The `weasyprint` render backend needs the `pdf` extra **and** system libraries
(pango/cairo/gdk-pixbuf). The default `pymupdf` backend needs none. Either
install the libraries or set `DOCUMENT_RENDER_BACKEND=pymupdf`.

---

## G. Provider connections

**Test** on `/app/providers` returns one of:

| Result | Meaning | Action |
| --- | --- | --- |
| `connected` | Endpoint and credentials work. | — |
| `authentication_failed` | Provider rejected the key. | Update the key. |
| `model_unavailable` | Endpoint reached but model missing. | Fix the default model id. |
| `endpoint_unreachable` | No response. | Check base URL/network. |
| `unsupported_protocol` | Provider type has no adapter. | Choose a supported protocol. |
| `unsafe_url` | URL is internal/unsafe (SSRF guard). | Use a public endpoint, or explicitly allow private for self-hosted. |

If a self-hosted endpoint (for example local Ollama) is wrongly rejected, ensure
the connection is allowed to use private addresses. See
[Security audit](security-audit.md).
