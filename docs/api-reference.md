# Book Fork — API Reference

> **Important.** Book Fork is a **server-rendered application**, not a public REST
> API. Almost every route returns an HTML page or an HTMX fragment. The only
> JSON endpoints are the health checks, `/metrics` and `GET /api/me`. This
> document exists so integrators and operators know exactly what each route
> accepts and returns.

> **Verification status.** Sourced from the routers in `app/api/routes/`, the
> dependency layer `app/api/dependencies.py`, and the exception taxonomy in
> `app/exceptions.py`.

---

## 1. Conventions

- **Base URL:** `APP_BASE_URL` (default `http://localhost:8000`), optionally
  mounted under `ROOT_PATH`.
- **Content type:** HTML routes are form-encoded or multipart on submission and
  return HTML. JSON routes return `application/json`.
- **CSRF:** every state-changing browser request requires a CSRF token, sent as
  the `X-CSRF-Token` header (HTMX injects it globally) or a `csrf_token` form
  field. Missing/invalid tokens return **403** `permission_denied`.
- **Auth:** `/app/*` and `/admin/*` require a signed-in user. `/admin/*`
  additionally requires the email to be in `admin.emails`.
- **Error body shape (JSON clients):** `{"code": "<machine_code>", "message": "<safe message>"}`.
  Browser routes render `pages/error.html` instead. See §5.
- **HTMX redirects:** successful form posts return HTTP 200 with an
  `HX-Redirect` header rather than a 3xx, so HTMX navigates the browser.

---

## 2. Public pages

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/` | Redirects to `/app` when signed in, otherwise `/login`. |
| GET | `/login` | Single sign-in/sign-up page (Google/GitHub); redirects to `/app` when already signed in. |
| GET | `/signup` | Redirects to `/login` — the OAuth page creates the account on first use. |
| GET | `/dashboard` | Redirects to `/app` (signed in) or `/login`. |

## 3. Authentication (`/auth/*`)

Sign-in is **OAuth2-only** (Google or GitHub) through PocketBase's manual code
exchange. `/login` lists the providers enabled in PocketBase; there is no
password, reset or verification flow. The callback is a top-level browser
navigation, so every failure redirects to `/login?error=<code>` rather than
returning JSON:

| Code | Message |
| --- | --- |
| `cancelled` | Sign-in was cancelled. |
| `state` | That sign-in link expired. Please try again. |
| `unavailable` | Could not reach the sign-in service. Please try again. |
| `failed` | We could not complete sign-in. Please try again. |
| `password` | Password sign-in is no longer available. Continue with Google or GitHub. |

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/auth/oauth2/callback` | Provider redirect target. Validates the signed `state` cookie, exchanges the code, sets the encrypted session cookie, then `303` to `/app`. |
| POST | `/login` | Removed password form. Old/cached forms get `303` (or `HX-Redirect`) to `/login?error=password`. |
| POST | `/auth/logout` | CSRF-protected. Clears the session and state cookies; returns `HX-Redirect: /login`. |


### `GET /api/me`

Returns the current user as JSON. Requires authentication.

```json
{ "id": "…", "email": "you@example.com", "name": "Ada", "verified": false }
```

## 4. Authenticated application (`/app/*`)

All routes require authentication and use the caller's PocketBase token.

### Dashboard and documents

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/app` and `/app/` | Dashboard page. |
| GET | `/app/translations` | Translation list page. |
| GET | `/app/documents` | Document list page. |
| GET | `/app/documents/{document_id}` | Document detail page. |
| GET | `/app/documents/{document_id}/source` | Streams the original source file as an attachment. 404 if not owned. |

### New translation

| Method | Path | Form fields | Notes |
| --- | --- | --- | --- |
| GET | `/app/translations/new` | — | New-translation form. |
| POST | `/app/translations/estimate` | `document_id`, `source_language`, `target_language`, `connection_id`, `quality_mode` | CSRF. Returns `partials/estimate.html` or `partials/estimate_error.html`. |
| POST | `/app/translations` | `document_id`, `source_language`, `target_language`, `connection_id`, `quality_mode`, `profile_id`, `persist_memory`, `upload` (file) | CSRF + translation rate limit. Uploads or reuses a document, checks size/upload/job limits, builds a plan and queues a job. Success: `HX-Redirect: /app/translations/{id}`. |

### Job page, actions and review

| Method | Path | Form fields | Notes |
| --- | --- | --- | --- |
| GET | `/app/translations/{job_id}` | — | Job page. 404 if not owned. |
| GET | `/app/translations/{job_id}/status` | — | `partials/job_status.html` for polling. |
| POST | `/app/translations/{job_id}/cancel` | — | CSRF. Sets `cancellation_requested`; returns the status fragment. |
| POST | `/app/translations/{job_id}/retry` | — | CSRF + retry rate limit. Only sensible for `failed`; sets `retry_mode=failed_only`, requeues, increments `retry_count`. |
| GET | `/app/translations/{job_id}/download` | query `format` (`pdf`/`epub`) | Streams an output attachment; falls back across available outputs. 404 when no output exists. |
| GET | `/app/translations/{job_id}/review` | — | Review page. |
| POST | `/app/translations/{job_id}/segments/{segment_id}` | `translated_text`, `approve` | CSRF. Updates the segment; `approve` sets status `validated`. Returns `partials/segment_row.html`. |

### Providers

| Method | Path | Form fields / notes |
| --- | --- | --- |
| GET | `/app/providers` | List connections. |
| GET | `/app/providers/new` | Add-provider form (enabled catalog protocols). |
| POST | `/app/providers` | CSRF. `name`, `provider_id`, `base_url`, `api_key`, `default_model`, `billing_mode` (`own_api`/`managed`). Stores the key encrypted. Success: `HX-Redirect: /app/providers`. |
| POST | `/app/providers/{id}/test` | CSRF + provider-test rate limit. Returns `partials/connection_test.html`; 404 if not owned. |
| POST | `/app/providers/{id}/toggle` | CSRF. Returns the updated provider row. |
| POST | `/app/providers/{id}/delete` | CSRF. Returns an empty 200. |

### Glossaries

| Method | Path | Form fields / notes |
| --- | --- | --- |
| GET | `/app/glossaries` | List glossaries. |
| GET | `/app/glossaries/new` | Create-glossary form. |
| POST | `/app/glossaries` | CSRF. `name`, `description`. Success: `HX-Redirect: /app/glossaries/{id}`. |
| GET | `/app/glossaries/{id}` | Glossary detail with terms. 404 if not owned. |
| POST | `/app/glossaries/{id}/terms` | CSRF. `source_language`, `target_language`, `source_term`, `target_term`, `preferred`, `forbidden`, `notes`. Returns a term row. |
| POST | `/app/glossaries/{id}/terms/{term_id}/delete` | CSRF. Returns empty 200. |

### Settings and memory

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/app/translation-memory` | Memory list (up to 200 entries). |
| GET | `/app/settings` | Settings hub. |
| GET | `/app/settings/languages` | Language registry + variants. |
| GET | `/app/settings/profiles` | Available profiles. |
| GET | `/app/settings/billing` | Wallet, recent transactions, usage. |

## 5. Admin (`/admin/*`)

Requires an authenticated user whose email is in `admin.emails` **and** a
configured `POCKETBASE_SERVICE_CREDENTIAL` (admin queries run with the superuser
token). CSRF is required on all mutations. `{slug}` is one of the resource slugs
listed in the [Admin Guide](admin-guide.md).

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/admin` and `/admin/` | Hub grouped by category. |
| GET | `/admin/metrics` | Metrics snapshot page. |
| GET | `/admin/prompt-versions/compare` | query `left`, `right` version ids. |
| GET | `/admin/{slug}` | List (≤ 200 records). |
| GET | `/admin/{slug}/new` | New form (if `can_create`). |
| POST | `/admin/{slug}` | Create (if `can_create`). |
| GET | `/admin/{slug}/{record_id}/edit` | Edit form. |
| POST | `/admin/{slug}/{record_id}` | Update (if `can_update`). |
| POST | `/admin/{slug}/{record_id}/delete` | Delete (if `can_delete`). |
| POST | `/admin/prompt-versions/{id}/activate` | Activate and archive siblings. |
| POST | `/admin/prompt-versions/{id}/archive` | Archive. |
| GET | `/admin/prompt-templates/{id}/new-version` | New-version form. |
| POST | `/admin/prompt-templates/{id}/new-version` | `body`, `notes`, `status`. |

## 6. Health and metrics

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | `{"status": "ok"}` — process liveness. |
| GET | `/health/ready` | JSON readiness. 200 when PocketBase and storage are reachable, else 503. Body: `{"ready": bool, "checks": [{"name", "ok", "detail"?}]}`. |
| GET | `/health/worker` | 200 when a worker heartbeated within 180 s, else 503. Body includes `alive` and the worker list. |
| GET | `/metrics` | Prometheus text exposition (per process). |

## 7. Interactive API documentation

When `ENABLE_DOCS` is true **and** `APP_ENV` is not `production`, FastAPI serves
`/docs` (Swagger UI), `/redoc` and `/openapi.json`. In production these are
disabled regardless of the setting.

## 8. Error codes

Domain errors define a stable `code` plus an HTTP status and a safe message. The
technical detail stays in logs. Business/validation errors use lower-case codes;
Phase 8 added the upper-case codes below.

| Code | HTTP | Meaning |
| --- | --- | --- |
| `validation_error` | 422 | Submitted data invalid. |
| `authentication_required` | 401 | No valid session. |
| `permission_denied` | 403 | Not permitted (includes CSRF failure). |
| `not_found` | 404 | Resource missing or not owned. |
| `conflict` | 409 | Conflicts with current state. |
| `rate_limited` | 429 | Too many requests. |
| `configuration_error` | 500 | Server misconfigured. |
| `prompt_render_error` | 422 | Prompt template could not render. |
| `ocr_unavailable` | 422 | Document needs OCR but none is configured. |
| `upstream_error` | 502 | An external dependency failed. |
| `DOCUMENT_UNSUPPORTED` | 422 | Document type not supported. |
| `DOCUMENT_CORRUPTED` | 422 | Document could not be read. |
| `DOCUMENT_TOO_LARGE` | 413 | Document exceeds the allowed size. |
| `LANGUAGE_UNSUPPORTED` | 422 | Language not supported. |
| `MODEL_UNSUPPORTED` | 422 | No configured model supports the language pair. |
| `PROVIDER_AUTH_FAILED` | 502 | Provider rejected the credentials. |
| `PROVIDER_RATE_LIMITED` | 503 | Provider is rate limiting. |
| `PROVIDER_TIMEOUT` | 504 | Provider did not respond in time. |
| `PROVIDER_UNAVAILABLE` | 502 | Provider unavailable. |
| `TRANSLATION_VALIDATION_FAILED` | 422 | A translation failed validation. |
| `OUTPUT_GENERATION_FAILED` | 500 | Translated document could not be generated. |
| `USAGE_LIMIT_EXCEEDED` | 429 | A configured usage limit was reached. |

The fallback codes `http_error` and `internal_error` are used for framework and
unexpected errors respectively.
