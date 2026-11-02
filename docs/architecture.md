# Book Fork — Architecture

Book Fork is a configuration-driven, multilingual document-translation SaaS. It is
**not** a fixed language-pair translator: source and target languages are data,
and translation is executed by provider-adapters behind a stable interface.

## 1. Guiding principles

1. **No translation behaviour is hardcoded.** Languages, language pairs,
   providers, models, endpoints, prompts, temperature, token limits, chunk/batch
   sizes, retries, glossary/TM rules, book pricing, quality profiles,
   capabilities and document limits all live in configuration
   (PocketBase records / job snapshots), not in Python.
2. **Capabilities stay in code.** Parsers, segmenters, placeholder protection,
   provider adapters, validation, exporters, pricing engines, the worker and the
   retry mechanism are reusable *capabilities*, not business configuration.
3. **Language-agnostic.** No `if language == "fa"`, no embedded RTL list. Language
   metadata (BCP-47, ISO 639, script, region, direction, native name, family)
   comes from the language registry.
4. **Provider-agnostic core.** The engine asks a provider to translate a fully
   resolved request; it never imports a specific vendor SDK.

## 2. Layering

```
HTTP / API layer        app/api/*            parsing, auth context, responses
        ↓
Service / auth layer    app/auth, app/services   use cases, orchestration
        ↓
Repository layer        app/repositories     PocketBase REST, external I/O
        ↓
Adapters                app/storage, providers, jobs
        ↓
PocketBase / object storage / LLM endpoints
```

Boundaries enforced by design:

- The API layer contains no business logic; it validates, authorizes, and renders.
- The worker never touches templates or routes.
- The translation engine knows nothing about HTTP.
- Provider adapters know nothing about PocketBase.
- Billing knows nothing about EPUB/PDF parsing.
- Raw PocketBase HTTP calls exist **only** in `app/repositories/pocketbase.py`.

### Composition root

`app/context.py` builds every adapter once at startup and stores it on
`app.state.ctx`. There is no module-level mutable global state; HTTP clients and
storage are owned by the context and closed in the FastAPI lifespan.

## 3. Module map

| Area | Location | Responsibility |
| --- | --- | --- |
| Config | `app/config.py` | Typed infra/secret settings (Pydantic Settings). |
| Context | `app/context.py` | Composition root + lifecycle. |
| API | `app/api/` | Routes, dependencies, exception mapping. |
| Auth | `app/auth/` | `AuthProvider` interface + PocketBase adapter + encrypted session cookies. |
| Security | `app/security/` | Secret encryption, CSRF, SSRF guards, rate limiting. |
| Repositories | `app/repositories/` | PocketBase REST client and transport schemas. |
| Storage | `app/storage/` | `Storage` protocol, local + S3 backends, factory. |
| Language | `app/language/` | Data-driven language model + registry interface. |
| Providers | `app/providers/` | Provider protocol, OpenAI-compatible adapter, encrypted credentials. |
| Translation | `app/translation/` | Plan, policy engine, translation engine, context, memory, glossary, validation, normalization. |
| Billing | `app/billing/` | Provider-cost and flat per-book pricing engines, estimation. |
| Jobs | `app/jobs/` | Persistent job store, leases, retry policy, worker config. |
| Services | `app/services/` | Health/readiness aggregation, data seeding. |
| Documents | `app/documents/` | Canonical model, EPUB/PDF adapters, segmentation, OCR, placeholders, safety. |
| Web | `app/web/` | Jinja templating, request-context middleware. |
| Product UI | `app/api/routes/`, `templates/` | Authenticated app, admin pages, HTMX fragments. |
| Worker | `worker/` | Durable runner, job executor, heartbeats, CLI. |

Phase 2 added: `app/workspaces/` (ownership/authz), `app/translation/policy.py`
(policy resolver), `app/prompts/renderer.py` (safe prompt rendering),
`app/billing/pricing.py` (provider cost and book pricing), `app/settings/service.py` (typed
settings), `app/language/` (registry, normalization, detection), the typed
repositories in `app/repositories/`, and the PocketBase schema/seeds. See
`docs/data-model.md`.

Validation and normalization are implemented as translation-phase capabilities
(`app/translation/validation.py`, `app/translation/normalization.py`) that plug
into the existing profile/policy configuration rather than new patterns. There
are no top-level `app/validation/` or `app/normalization/` packages.

## 4. Request lifecycle (browser)

1. `RequestContextMiddleware` ensures a CSRF token exists and resolves the
   encrypted session cookie into a user via `AuthProvider.refresh` (rotating the
   cookie when PocketBase issues a new token).
2. A route collects input, enforces CSRF/rate limits via dependencies, delegates
   to the auth service, and sets/clears the session cookie.
3. Templates render either the full application shell or only the
   `#app-content` region, depending on the `HX-Request` header.
4. Expected domain errors are mapped to truthful HTTP status codes by exception
   handlers; unexpected errors are logged and returned as 500.

## 5. Authentication & sessions

- PocketBase is the identity system; the application depends only on the
  `AuthProvider` protocol (`app/auth/base.py`).
- Sign-in is **OAuth2-only** (Google / GitHub). `/login` asks PocketBase for the
  enabled providers, keeps each one-off `state` + PKCE verifier in a signed,
  HttpOnly 10-minute cookie, and exchanges the authorization code at
  `/auth/oauth2/callback`. Sign-up is the same action: PocketBase creates the
  record on first sign-in and links existing users by verified email.
- The PocketBase bearer token is **never** exposed to JavaScript. It is encrypted
  with Fernet (`ENCRYPTION_KEY`) and stored in an **HttpOnly**, signed-by-
  construction session cookie.
- CSRF uses a signed double-submit token in an HttpOnly cookie, echoed via the
  `X-CSRF-Token` header (HTMX injects it globally) or a `csrf_token` form field.
- Authorization is enforced server-side; PocketBase collection rules provide
  defense in depth.

## 6. Storage

`Storage` (`app/storage/base.py`) abstracts byte storage. `LocalStorage` is the
development backend; `S3Storage` (boto3, dispatched to threads via anyio) is the
production backend. Document-processing code depends on the protocol, never on a
path or bucket.

## 7. Frontend construction

Server-rendered Jinja2 with HTMX (navigation/mutations) and Alpine.js (local UI
state) over Tailwind CSS + daisyUI. A persistent shell (`#app-content`) is the
swap target for internal navigation. The visual system is the shared "Warm Paper
Workspace" theme (cream canvas, single amber action colour, flat 6px geometry,
hairline borders, self-hosted DM Sans) implemented as a custom daisyUI 5 theme
with no bespoke component classes; tokens and rules live in
`static/css/input.css` and [`../DESIGN.md`](../DESIGN.md).

## 8. Package & version decisions

Latest **stable** releases were verified at implementation time (see
`docs/decisions/0001-stack-and-versions.md`). Exact resolved versions are pinned
in `uv.lock` and `package-lock.json`.

| Component | Constraint | Resolved | Notes |
| --- | --- | --- | --- |
| Python | 3.14.x | 3.14.8 | via uv-managed CPython |
| Node.js | 24 LTS | 24.21.0 | LTS "Krypton" |
| FastAPI | ≥0.142.2 | 0.142.2 | |
| Starlette | (transitive) | 1.7.0 | |
| Pydantic | ≥2.13.5 | 2.13.5 | |
| pydantic-settings | ≥2.15.0 | 2.15.0 | |
| Uvicorn | ≥0.54.0 | 0.54.0 | |
| Jinja2 | ≥3.1.6 | 3.1.6 | |
| httpx | ≥0.28.1 | 0.28.1 | |
| anyio | ≥4.15.1 | 4.15.1 | |
| tenacity | ≥9.1.4 | 9.1.4 | |
| structlog | ≥26.1.0 | 26.1.0 | |
| python-multipart | ≥0.0.32 | 0.0.32 | |
| itsdangerous | ≥2.2.0 | 2.2.0 | |
| cryptography | ≥50.0.2 | 50.0.2 | Fernet. |
| email-validator | ≥2.3.0 | 2.3.0 | |
| boto3 | ≥1.43.108 | 1.43.108 | S3 backend. |
| langcodes | ≥3.5.1 | 3.5.1 | BCP-47 parsing/normalization. |
| language-data | ≥1.4.0 | 1.4.0 | CLDR name data for langcodes. |
| Babel | ≥2.18.0 | 2.18.0 | CLDR locales, script, direction. |
| py3langid | ≥0.4.0 | 0.4.0 | Offline language detection. |
| PyMuPDF | ≥1.28.2 | 1.28.2 | PDF extraction **and** Story-based book PDF rendering. |
| lxml | ≥6.1.3 | 6.1.3 | EPUB XHTML/OPF handling. |
| pysbd | ≥0.3.4 | 0.3.4 | Multilingual sentence segmentation. |
| WeasyPrint | ≥70.0 | optional | Alternative PDF rendering (the `pdf` extra). |
| Tailwind CSS | 4.x | 4.3.3 | CSS-first v4. |
| daisyUI | 5.x | 5.7.47 | Tailwind plugin. |
| Alpine.js | 3.x | 3.17.4 | |
| **HTMX** | **stable** | **2.0.11** | See below. |

### HTMX: 2.x, not 4.x

The brief lists "HTMX 4.x". At implementation time HTMX **4.0.0 is published only
as a prerelease** (`next` dist-tag); the latest stable release is `2.0.11`. The
package policy forbids prereleases for production, so Book Fork uses HTMX 2.0.11 and
will move to 4.x once it reaches a stable release.

### Deferred dependencies

`EbookLib` is not used: EPUB is handled with the standard library `zipfile` plus
`lxml`, which gives the fine-grained structural and safety control the engine
needs. `WeasyPrint` is an optional extra because it requires system libraries;
the default `pymupdf` book renderer needs none. Future OCR providers (tesseract,
paddleocr, cloud) are behind the `OcrProvider` interface.

### Known advisories

`npm audit` reports advisories in the **dev-only** `@tailwindcss/cli → @parcel/watcher
→ micromatch → braces` chain. The offered "fix" downgrades Tailwind and does not
affect the shipped runtime; it is accepted for now and tracked.

## 9. Security posture (Phase 1)

- `.env` is git-ignored; `.env.example` contains placeholders only.
- Secrets encrypted at rest (Fernet); sensitive log keys redacted.
- HttpOnly session cookie, derived `Secure` in production, `SameSite` configurable.
- CSRF for all state-changing browser requests.
- SSRF guard for user-supplied provider endpoints (`app/security/urls.py`).
- Storage keys validated against path traversal.
- Auth endpoints rate-limited; errors mapped without leaking upstream detail.
- Trusted-host, transport size ceiling, and optional CORS configuration.

## 10. Phase status and deferred work

**Phase 1** delivered the runnable foundation (API, auth, storage, worker,
health, assets). **Phase 2** delivered the configuration-driven data model
(`docs/data-model.md`). **Phase 3** delivered the format-agnostic document engine
(`docs/documents.md`). **Phase 4** delivered the universal translation engine
(`docs/translation.md`). **Phase 5** delivered the durable worker (`docs/worker.md`). **Phase 6** made it
commercially usable: pluggable providers with managed/own-API billing modes,
encrypted user keys, SSRF-protected custom endpoints, connection testing,
capability- and cost-aware model routing with quality tiers, generic provider
costing, and flat per-book orders (`docs/providers-and-billing.md`). **Phase 7**
delivered the product UI: application shell, dashboard, new-translation workflow
with estimates, job pages with HTMX progress and actions, review, providers,
glossaries, memory, settings and protected admin pages (`docs/ui.md`). **Phase 8**
hardened and completed it: a declarative admin area (CRUD for every collection,
prompt versioning, model/language and pricing management), stable machine-readable
error codes, structured events and lightweight metrics, security headers, expanded
rate limiting and settings-driven abuse limits, configurable data retention,
worker liveness, production containers with health checks, and a security audit
(`docs/security-audit.md`, `docs/deployment.md`).

The frontend is fully functional and styled with the bespoke "Warm Paper
Workspace" system (see [`../DESIGN.md`](../DESIGN.md) and `docs/ui.md`); the
design is applied through the daisyUI theme and component classes without
changing routing or handlers.
