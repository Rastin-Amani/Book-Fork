# Changelog

All notable changes to Book Fork. This project uses a phase-based build; the
current release is **0.6.0** and is described below as delivered phases. Dates
come from the project’s architecture decision records.

## [0.6.0] — 2026-11-02

**Status: unified interface release.**

### Interface

- Replace the bespoke component layer with daisyUI primitives and semantic
  theme tokens; the stylesheet now holds only the theme, self-hosted DM Sans and
  a minimal element base.
- Rebuild the application shell, auth split panel, dashboard, settings and admin
  surfaces on the shared “Warm Paper Workspace” system used by the marketing
  site.
- Give the new-translation workflow a single form with a sticky action rail and
  replace ad-hoc health rows with one consistent table, card and badge language.
- Add breadcrumb navigation, cleaner empty states, a stats strip, and a single
  ink chamber on the dashboard for hierarchy.
- Keep one amber action per view and remove named palette tokens so every
  surface follows the theme.

### Documentation

- Rewrite `DESIGN.md` around the token-only system, daisyUI primitive mapping
  and service-first layout rules.
- Align the UI, architecture and development guides with the implemented
  interface.

### Known limitations at 0.6.0

- The combined web/worker container is intended for one replica because worker
  slot ids are container-local.
- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.

## [0.5.1] — 2026-10-30

**Status: worker recovery fixes.**

### Worker

- Rebuild a missing `canonical.json` by re-parsing the stored source and
  restoring its assets, so a job can finalize after a storage loss without
  re-translating any segment.
- Report the exception class for an unexpected worker error while keeping the
  full traceback in the worker log. Raw exception text is not shown in the job
  UI.

### Known limitations at 0.5.1

- The combined web/worker container is intended for one replica because worker
  slot ids are container-local.
- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.

## [0.5.0] — 2026-10-30

**Status: provider recovery and worker resilience.**

### Providers

- Add in-place API key rotation at `POST /app/providers/{id}/credential`, so a
  rejected key can be replaced without deleting the connection and orphaning
  jobs pinned to it.
- Expose a **Key** control in each provider row; it expands inside the row
  instead of a clipped table popover and labels the password input.
- Validate blank keys, enforce workspace ownership and cover the route with
  integration tests.

### Worker

- Stop on the first batch when the provider rejects authentication; fail with
  `PROVIDER_AUTH_FAILED` and an actionable message instead of writing thousands
  of doomed attempts.
- Requeue a job when PocketBase or storage raises `UpstreamError`, clearing the
  lease and keeping completed segments. Requeues are bounded at 20.
- Include the transport error class and request path in upstream error messages.

### Translation memory

- Load approved entries for a language pair once per job and index them in
  memory, instead of issuing one PocketBase query per segment.

### Known limitations at 0.5.0

- The combined web/worker container is intended for one replica because worker
  slot ids are container-local.
- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.

## [0.4.2] — 2026-10-25

**Status: retry, storage and transport resilience.**

### Worker

- A retry now resumes both failed and never-attempted pending segments while
  keeping validated/translated work. Previously a failed-only filter could
  complete a job with most of the book untranslated.
- Remove the now-unused `retry_mode` job metadata and align the worker and API
  docs with the resume behaviour.

### Documents & storage

- `materialize` checks storage before opening a temp file and raises a clear
  404 with a re-upload message when a record's bytes are missing.
- The container creates `/app/var/storage` for the unprivileged runtime user.

### PocketBase

- Transport retries rise from 3 to 5 attempts, with backoff starting at 0.5 s
  and capped at 4 s, so a short restart no longer fails a request or job.

### Known limitations at 0.4.2

- The combined web/worker container is intended for one replica because worker
  slot ids are container-local.
- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.

## [0.4.1] — 2026-10-25

**Status: container build cleanup.**

### Build

- Stop precompiling Python bytecode during the image build. The runtime
  already sets `PYTHONDONTWRITEBYTECODE=1`, so the image and build no longer
  carry generated `.pyc` files.
- A cold start now compiles modules in memory instead of reading cached
  bytecode from the image.

## [0.4.0] — 2026-10-25

**Status: single-container worker pool.** A rebuilt image now starts the web
process and a supervised translation worker pool together.

### Deployment

- Add `docker-entrypoint.sh` as the image command: it runs Uvicorn plus
  `WORKERS` supervised worker processes (default `1`).
- Give each slot a stable `WORKER_ID` so a restart updates its own workers row,
  restart crashed slots in place, and forward `SIGTERM`/`SIGINT` so in-flight
  jobs are requeued instead of losing a live lease.
- Put the virtualenv on `PATH` so the health check and entrypoint use the
  installed Python.
- Keep `compose.yaml` web-only with `WORKERS=0` because it already has a
  dedicated worker service.
- Document the Dockerfile and compose behaviour, and cover slot identity,
  signal forwarding and crash restart in tests.

### Known limitations at 0.4.0

- Worker slot ids are container-local; run one replica of the combined
  web/worker container, or give additional replicas distinct deployments.
- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.
- Only the `openai_compatible` and `ollama` provider protocols have adapters.
- No self-service card checkout; book orders are reconciled externally.
- Per-process rate limiting and metrics are not shared across replicas.

## [0.3.1] — 2026-10-25

**Status: UI cache fix.** The app shell now busts cached bundles on deploy and
provider buttons keep their icon size.

### Web

- Append the release version to the `/static/css/app.css` and
  `/static/js/app.js` URLs so a deploy cannot serve a stale bundle.
- Give the Google and GitHub SVGs explicit width and height alongside their
  utility classes so the provider icon stays 18px.
- Cover the versioned asset URLs in the web integration tests.

## [0.3.0] — 2026-10-25

**Status: OAuth-only sign-in.** Google and GitHub are now the only ways to sign
in. Password, OTP/MFA, password-reset and email-verification flows are removed.

### Authentication

- Replace the email/password login, signup, reset and verification pages with a
  single `/login` page offering Google and GitHub.
- Use PocketBase's OAuth2 authorization-code flow with PKCE and a signed,
  HttpOnly, 10-minute `state` cookie; the callback rejects missing, forged,
  expired and non-ASCII state.
- Treat sign-in and sign-up as one action: the provider creates the account on
  first use and links an existing record by verified email.
- Redirect `/signup` to `/login`; old password form posts return a friendly
  "password sign-in is no longer available" message.
- Add `scripts/configure_auth.py` to push Google/GitHub credentials into
  PocketBase, and a migration that disables password, OTP and MFA auth.
- Add the four `GOOGLE_OAUTH_*` / `GITHUB_OAUTH_*` environment variables and
  remove the signup and password-reset rate-limit settings.

### Build & operations

- Give the container user a writable uv cache under `/app/.cache/uv` so the web
  and worker processes start as non-root.

### Known limitations at 0.3.0

- Google and/or GitHub must be configured in PocketBase; there is no password
  fallback.
- A second sign-in attempt for the same provider invalidates an earlier tab's
  state cookie.
- Only the `openai_compatible` and `ollama` provider protocols have adapters.
- No self-service card checkout; book orders are reconciled externally.
- Per-process rate limiting and metrics are not shared across replicas.

## [0.2.0] — 2026-10-25

**Status: flat per-book pricing and document-quality release.** Managed
translation is sold as one flat-priced book order instead of token credits, and
PDF/EPUB output handles structured RTL books correctly.

### Billing

- Replaced token credits and the customer wallet with a flat managed-book price:
  **$7 per book up to 1,000 pages**, plus $7 per additional 1,000-page block.
- Own-API connections are free; provider cost is still recorded internally for
  margin monitoring.
- Each managed job snapshots its order (pages, blocks, amount, currency) on the
  job; failed and cancelled jobs are not charged.
- The billing page lists book orders; payment collection is reconciled outside
  the app.
- Removed credit reservation/settlement from the worker and wallet
  administration from the admin area.

### Documents

- Detect and strip PDF list markers (Latin and Arabic-Indic) and remember
  ordered/unordered style.
- Render list items with correct RTL placement in PDF and as real `ul`/`ol`
  elements in EPUB.
- Make covers, running heads, contents titles and contents-page page numbers
  direction-aware.
- Turn contents rows into reliable internal links, bound and deduplicate the
  menu, and keep headings from being orphaned at a page bottom.
- Split font-size chapter titles from weight-only subheads so every bold line no
  longer starts a page.

### Web & operations

- Root now redirects to the workspace (`/app`) or login instead of a marketing
  page.
- Server-rendered release version in both shells, API metadata and worker
  registration.
- Removed redundant job-page reads and parallelised settings, policy and paged
  repository lookups.
- New Book Fork mark, favicon set, Apple touch icon and web manifest.

### Known limitations at 0.2.0

- Only the `openai_compatible` and `ollama` provider protocols have adapters.
- No self-service card checkout; book orders are reconciled externally.
- EPUB and PDF only; ingestion does not accept the `txt`/`docx` extensions listed
  in the seed settings.
- Glossary attachment is not exposed in the UI and memory approval is admin-only.
- Per-process rate limiting and metrics are not shared across replicas.

## [0.1.0] — 2026-10-05

**Status: Phase 8 complete.** Book Fork 0.1.0 is a configuration-driven,
provider-agnostic multilingual document-translation service.

### Phase 1 — Foundation

- FastAPI application skeleton, typed settings, composition root, health and
  readiness checks.
- PocketBase-backed authentication with encrypted, HttpOnly session cookies.
- CSRF protection, SSRF guards, rate limiting, storage abstraction (local + S3),
  durable worker entry point, structured logging, frontend asset pipeline.

### Phase 2 — Configuration-driven data model

- Languages, providers, models, capabilities, prompts, profiles, glossaries,
  memory, credits and settings as PocketBase records.
- Workspace tenancy with roles and server-side authorization defense in depth.
- Reproducible migrations (`pb_migrations/`) and idempotent seeds (`seeds/`).
- Typed repository layer and schema sync for remote instances.

### Phase 3 — Document engine

- Canonical, format-agnostic document model with deterministic ids.
- Safe EPUB (ZIP/lxml) and PDF (PyMuPDF) parsing; placeholder protection;
  structure-aware segmentation; OCR interface.
- Book output: print-ready PDF and valid EPUB 3, with bundled fonts and RTL
  support.

### Phase 4 — Universal translation engine

- Immutable `TranslationPlan` executed against a provider-agnostic interface.
- Policy engine resolving profile/connection/model via capability matrix.
- Structured output with coverage validation; context building; exact-match
  translation memory; glossary retrieval; normalization and validation;
  retries and fallback/pivot strategies.

### Phase 5 — Durable worker

- Separate worker process with bounded concurrency, per-job leases and
  heartbeats, stale-job recovery, resumable/idempotent execution, cooperative
  cancellation, and per-segment retries with context repair.

### Phase 6 — Providers, routing & billing

- Pluggable providers with `managed` and `own_api` billing modes; encrypted user
  credentials; SSRF-protected custom endpoints; connection testing.
- Capability- and cost-aware model routing with quality tiers; generic pricing.
- Auditable credit ledger (reserve/settle/refund) with idempotent references.

### Phase 7 — Product UI

- Application shell, dashboard, new-translation workflow with estimates, job
  pages with HTMX progress and state-gated actions, review, providers,
  glossaries, memory, settings and protected admin pages.

### Phase 8 — Admin, hardening & operations

- Declarative admin area: CRUD for every collection, prompt versioning and
  comparison, model/language and credit management.
- Stable machine-readable error codes; structured events; lightweight metrics.
- Security headers, expanded rate limiting, settings-driven abuse limits,
  configurable retention, worker liveness, production containers with health
  checks, and a security audit.
- Bespoke “Warm Paper Workspace” design system (cream canvas, amber action,
  flat geometry, self-hosted DM Sans) mapped onto daisyUI 5.

### Known limitations at 0.1.0

- EPUB and PDF only (the seeded `upload.allowed_extensions` also lists `txt` and
  `docx`, which ingestion does not accept).
- Only the `openai_compatible` and `ollama` provider protocols have adapters;
  the seeded Anthropic, Google Gemini and Custom endpoint records are stubs and
  return `unsupported_protocol` until an adapter is added.
- Glossary attachment to a job/profile is not exposed in the UI.
- Translation-memory approval is admin-only.
- No self-service credit purchase.
- Single personal workspace per user; no invitation flow.
- Per-process rate limiting/metrics are not shared across replicas.
- Email delivery depends on PocketBase’s mailer.

See the [User Guide](docs/user-guide.md#13-current-limitations-verified) and
[Troubleshooting](docs/troubleshooting.md) for details.
