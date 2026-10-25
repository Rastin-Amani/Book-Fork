# Book Fork

Multilingual document-translation SaaS. Book Fork translates **EPUB and PDF
documents between arbitrary source and target languages** using configurable LLM
providers. Users either buy a Book Fork-managed book ($7 flat) or connect their own
LLM endpoint and use Book Fork free, paying the provider directly.

It is configuration-driven, modular, resumable, and provider-agnostic: nothing
about translation behaviour (languages, providers, models, prompts, limits,
pricing) is hardcoded.

> **Status: Phase 8 complete.** Phase 1 foundation, Phase 2 configuration-driven
> data model ([`docs/data-model.md`](docs/data-model.md)), Phase 3 document engine
> ([`docs/documents.md`](docs/documents.md)), Phase 4 translation engine
> ([`docs/translation.md`](docs/translation.md)), Phase 5 durable worker
> ([`docs/worker.md`](docs/worker.md)), Phase 6 providers/routing/billing
> ([`docs/providers-and-billing.md`](docs/providers-and-billing.md)), Phase 7
> product UI ([`docs/ui.md`](docs/ui.md)), Phase 8 admin/testing/security/
> observability/deployment. The admin area is declarative CRUD plus prompt, model,
> language management; see [`docs/security-audit.md`](docs/security-audit.md),
> [`docs/deployment.md`](docs/deployment.md) and [`docs/configuration.md`](docs/configuration.md).
> The UI carries a bespoke "Warm Paper Workspace" design system — a custom
> daisyUI theme, self-hosted DM Sans, and a flat cream/amber visual language.
> See [`DESIGN.md`](DESIGN.md) and [`docs/ui.md`](docs/ui.md).

---

## Stack

- **Backend:** Python 3.14, FastAPI, Pydantic v2, Uvicorn, Jinja2, httpx,
  anyio, tenacity, structlog — managed by `uv`.
- **Frontend:** server-rendered Jinja2, HTMX 2, Alpine.js 3, Tailwind CSS 4,
  daisyUI 5 — built with Node 24 LTS and npm.
- **Data:** PocketBase (REST, via a dedicated repository layer).
- **Storage:** pluggable local filesystem or S3-compatible object storage.

See [`docs/architecture.md`](docs/architecture.md) for the full design and version
table.

---

## Quickstart

Prerequisites: [`uv`](https://docs.astral.sh/uv/) and Node.js 24 (with npm). A
local PocketBase is optional — tests do not require one.

```bash
# 1. Install dependencies
uv sync
npm install

# 2. Configure
cp .env.example .env
uv run python scripts/generate_secrets.py     # paste the values into .env

# 3. Build frontend assets (vendor JS + Tailwind/daisyUI)
npm run build

# 4. Run
uv run fastapi dev app/main.py                # web + API on :8000
uv run python -m worker.main                  # worker (separate terminal)

# …or via the Makefile (uses .venv/bin/python, loads .env from the repo root)
make web                                       # web + API on :8000
make worker                                    # worker (separate terminal)
make worker-once                               # process one queued job, then exit

# 5. Seed reference data (idempotent; needs a superuser credential)
POCKETBASE_SERVICE_CREDENTIAL='admin@example.com:password' uv run python scripts/seed.py

# 6. Sign-in providers (Google / GitHub; credentials in .env, idempotent)
uv run python scripts/configure_auth.py
```

Open http://localhost:8000.

### With Docker (includes PocketBase)

```bash
cp .env.example .env   # fill secrets
docker compose up --build
```

### PocketBase

`pb_migrations/` defines the schema (starting with the `users` auth collection).
Run PocketBase against it:

```bash
pocketbase serve --http=0.0.0.0:8090 --migrationsDir=./pb_migrations
```

---

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /health` | Liveness — the process is up. |
| `GET /health/ready` | Readiness — PocketBase and storage are reachable (503 when not). |

---

## Development commands

| Command | Purpose |
| --- | --- |
| `uv sync` | Install Python dependencies. |
| `npm install` | Install JS dependencies. |
| `npm run build` | Vendor HTMX/Alpine and compile CSS. |
| `npm run dev:css` | Tailwind watch mode. |
| `uv run fastapi dev app/main.py` | Development server. |
| `make web` / `make worker` | Same, pinned to `.venv/bin/python` (see `Makefile`). |
| `uv run python -m worker.main` | Worker process. |
| `uv run pytest` | Run tests. |
| `uv run ruff check .` | Lint. |
| `uv run ruff format --check .` | Format check. |
| `uv run mypy .` | Static type checking. |

More detail in [`docs/development.md`](docs/development.md) and
[`docs/configuration.md`](docs/configuration.md).

---

## Project layout

```
app/         FastAPI application, services, repositories, adapters
worker/      Background worker entrypoint
templates/   Jinja server-rendered views (full page or HTMX region)
static/      CSS/JS sources; app.css and vendor JS are generated
pb_migrations/  PocketBase schema migrations
scripts/     Developer utilities
tests/       unit / integration / e2e
docs/        Architecture, configuration, development, ADRs
```

---

## Documentation

| I want to… | Read |
| --- | --- |
| Use Book Fork | [`docs/user-guide.md`](docs/user-guide.md) · [`docs/faq.md`](docs/faq.md) · [`docs/troubleshooting.md`](docs/troubleshooting.md) |
| Administer / operate it | [`docs/admin-guide.md`](docs/admin-guide.md) · [`docs/operations.md`](docs/operations.md) · [`docs/deployment.md`](docs/deployment.md) |
| Understand the design | [`docs/architecture.md`](docs/architecture.md) · [`docs/data-model.md`](docs/data-model.md) · [`docs/documents.md`](docs/documents.md) · [`docs/translation.md`](docs/translation.md) · [`docs/worker.md`](docs/worker.md) · [`docs/providers-and-billing.md`](docs/providers-and-billing.md) · [`docs/ui.md`](docs/ui.md) |
| Integrate / debug | [`docs/api-reference.md`](docs/api-reference.md) · [`docs/configuration.md`](docs/configuration.md) |
| Contribute | [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`docs/development.md`](docs/development.md) · [`docs/testing.md`](docs/testing.md) |

Full index: [`docs/README.md`](docs/README.md). History: [`CHANGELOG.md`](CHANGELOG.md).

---

## Security notes

- `.env` is git-ignored; `.env.example` holds placeholders only.
- Provider API keys and the session token are encrypted at rest (Fernet).
- Session cookie is HttpOnly and `Secure` in production.
- CSRF protection on browser mutations; SSRF guard for user-supplied endpoints;
  path-traversal-safe storage keys; rate-limited auth; sensitive log redaction.

---

## License

MIT
