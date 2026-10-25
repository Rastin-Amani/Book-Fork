# Changelog

All notable changes to Book Fork. This project uses a phase-based build; the
current release is **0.2.0** and is described below as delivered phases. Dates
come from the project’s architecture decision records.

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
