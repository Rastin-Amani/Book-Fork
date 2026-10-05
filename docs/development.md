# Development

## Prerequisites

- Python **3.14** (managed by `uv`; no system install needed)
- Node.js **24 LTS** and npm
- [`uv`](https://docs.astral.sh/uv/)
- PocketBase 0.40.x (optional locally; tests do not require it)

## Setup

```bash
uv sync
npm install
cp .env.example .env
uv run python scripts/generate_secrets.py   # paste into .env
npm run build           # vendor JS + compile Tailwind/daisyUI
```

## Run

```bash
# API + web (reload)
uv run fastapi dev app/main.py

# Worker (separate terminal)
uv run python -m worker.main

# Tailwind watch (separate terminal)
npm run dev:css
```

Visit http://localhost:8000. Health: `/health`, readiness: `/health/ready`.

## Commands

| Command | Purpose |
| --- | --- |
| `uv sync` | Install Python deps from `uv.lock`. |
| `npm install` | Install JS deps from `package-lock.json`. |
| `npm run build` | Vendor HTMX/Alpine + build `static/css/app.css`. |
| `npm run dev:css` | Tailwind CSS watch mode. |
| `uv run fastapi dev app/main.py` | Development server. |
| `uv run python -m worker.main` | Worker process. |
| `uv run python scripts/seed.py` | Apply seeds (idempotent). |
| `uv run python scripts/push_schema.py` | Push schema to a remote PocketBase. |
| `uv run pytest` | Test suite (hermetic; no PocketBase needed). |
| `uv run ruff check .` | Lint. |
| `uv run ruff format --check .` | Format check. |
| `uv run mypy .` | Static types (strict). |
| `docker compose up --build` | Full local stack incl. PocketBase. |

## Quality gates

Run before committing:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## Tests

Tests are hermetic — they never require a live PocketBase. Upstream HTTP is
mocked with `httpx.MockTransport` and the application context is built from test
settings. Layout:

- `tests/unit/` — config, crypto, CSRF, SSRF, rate limiting, storage, PB client.
- `tests/integration/` — health, pages, auth flow, CSRF enforcement, HTMX
  partial rendering.

## PocketBase

`pb_migrations/` contains the reproducible schema. Apply it by running
PocketBase with this directory:

```bash
pocketbase serve --http=0.0.0.0:8090 --migrationsDir=./pb_migrations
```

`--automigrate` is on by default, so collection edits made in the Dashboard
generate migration files here — review and commit them.

### Seeding

Seeds live in `seeds/` and are applied through the repository layer
(idempotent, no credentials):

```bash
# POCKETBASE_SERVICE_CREDENTIAL may be a superuser token or "identity:password"
uv run python scripts/seed.py
```

### Remote instances

PocketBase migrations only run inside the server process. If your instance
cannot run this repository's migrations, push the already-migrated schema
through the Admin API:

```bash
uv run python scripts/push_schema.py \
  --source-db /path/to/pb_data/data.db \
  --target-url https://pocketbase.example.com \
  --identity admin@example.com --password '...'
```


## Frontend assets

HTMX, Alpine, Tailwind and daisyUI are compiled/vendored into `static/`
(`app.css` and `js/vendor/` are git-ignored generated output). Run `npm run build`
after a fresh clone or whenever `input.css` changes.

The visual system is the bespoke “Warm Paper Workspace” daisyUI theme; tokens
live in `static/css/input.css` and the rules in [`../DESIGN.md`](../DESIGN.md).
