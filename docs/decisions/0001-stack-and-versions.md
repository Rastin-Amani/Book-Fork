# ADR 0001 — Stack and version decisions

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Book Fork targets Python 3.14, Node 24 LTS, and current stable releases of the
backend and frontend stack. The brief's package policy requires verifying the
latest **stable** release at implementation time, rejecting alpha/beta/dev
builds, recording decisions, and committing lockfiles.

## Decision

Use the versions pinned in `uv.lock` / `package-lock.json`. Verified latest
stable, Python-3.14-compatible releases:

- Python 3.14.8, Node.js 24.21.0 (LTS "Krypton").
- FastAPI 0.142.2, Starlette 1.7.0, Pydantic 2.13.5, pydantic-settings 2.15.0.
- Uvicorn 0.54.0, Jinja2 3.1.6, httpx 0.28.1, anyio 4.15.1, tenacity 9.1.4,
  structlog 26.1.0, python-multipart 0.0.32, itsdangerous 2.2.0,
  cryptography 50.0.2, email-validator 2.3.0, boto3 1.43.108.
- Tailwind CSS 4.3.3, daisyUI 5.7.47, Alpine.js 3.17.4.
- **HTMX 2.0.11** (not 4.x — see below).
- Tooling: Ruff 0.16.10, mypy 2.4.0, pytest 9.1.1, pytest-asyncio 1.4.0.

## Notable decisions

### HTMX 2.x instead of 4.x

The brief names HTMX 4.x. At decision time, `htmx.org@4.0.0` is published only on
the npm `next` (prerelease) dist-tag; `latest` is `2.0.11`. The package policy
forbids prereleases in production, so we adopt the latest stable and will upgrade
when 4.x is stable.

### Deferred document-processing libraries

PyMuPDF, EbookLib, lxml, WeasyPrint and Unicode/language libraries are not
installed yet. Phase 1 is foundation-only; adding unused heavyweight
infrastructure would violate the "no infrastructure without a clear reason"
policy. Their Python-3.14 compatibility will be verified when the document
pipeline is built.

### boto3 for S3

The storage abstraction requires an S3-compatible backend. boto3 is the
established, maintained client; calls are dispatched to threads via anyio so they
never block the event loop.

### Test tooling: Starlette `TestClient` deprecation

Starlette 1.7 deprecates using `httpx` with its `TestClient` (it prefers a new
`httpx2` package). This affects test tooling only, not the runtime. We suppress
that single warning in `pyproject.toml` rather than add a second HTTP client
dependency; the application runtime continues to use `httpx` directly.

### Dev-only npm advisories accepted

`npm audit` flags the `@tailwindcss/cli → @parcel/watcher → micromatch → braces`
chain. The advisory is in a build-time-only tool and never ships in the runtime;
the suggested remediation downgrades Tailwind. Accepted and tracked.

## Consequences

- Reproducible installs via committed `uv.lock` and `package-lock.json`.
- Python 3.14 is fully managed by `uv`; contributors need no system Python.
- HTMX 2.x is stable and adequate for the shell; upgrading to 4.x is a
  contained change (attribute semantics, not architecture).
- Adding document-processing dependencies later is a scoped, deliberate step.

> **Update (Phases 3–8).** The deferred libraries were added as each phase
> needed them: PyMuPDF, lxml, pysbd, WeasyPrint (optional `pdf` extra),
> langcodes, language-data, Babel and py3langid are now declared in
> `pyproject.toml` and resolved in `uv.lock` (see the version table in
> [`../architecture.md`](../architecture.md#8-package--version-decisions)).
> EbookLib remains intentionally unused. HTMX is still 2.0.11.
