# Contributing to Book Fork

Thanks for helping. This file covers how to set up, where code goes, and what
“done” means. For detail see the [Development](docs/development.md) and
[Testing](docs/testing.md) guides.

---

## 1. Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (manages Python 3.14 for you)
- Node.js **24 LTS** and npm
- PocketBase 0.40.x (optional locally — tests do not need it)

## 2. Setup

```bash
uv sync
npm install
cp .env.example .env
uv run python scripts/generate_secrets.py   # paste the three values into .env
npm run build                                # vendor JS + compile Tailwind/daisyUI
```

Run the app and worker in separate terminals:

```bash
uv run fastapi dev app/main.py
uv run python -m worker.main
```

The worker requires `POCKETBASE_SERVICE_CREDENTIAL`; the web app does not.

## 3. Definition of done

All four gates must pass before a change is complete:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

`make check` runs lint, typecheck and tests together. mypy is **strict**; Ruff
enforces a security lint set, and warnings fail the test suite (two documented
ignore exceptions).

## 4. Project rules

Book Fork has a few load-bearing conventions. Please respect them:

1. **No hardcoded translation behaviour.** Languages, pairs, direction, providers,
   models, prompts, pricing, credit prices, chunk/batch sizes and file limits are
   **data** (PocketBase records / job snapshots), never Python constants. See
   `docs/architecture.md` and the hardcoding audit in `docs/security-audit.md`.
2. **Respect the boundaries.** Raw PocketBase HTTP lives only in
   `app/repositories/pocketbase.py`; the worker never imports templates/routes;
   the translation engine knows nothing about HTTP; provider adapters know
   nothing about PocketBase.
3. **Authorization is server-side.** Never rely on hidden UI. Cross-workspace
   access must be denied in code (and is tested).
4. **Secrets stay out of data.** `seeds/` must contain no credentials (enforced
   by a test). Provider keys are encrypted and never rendered.
5. **Failed attempts are never silently converted into success.** Structured
   output is validated; malformed responses fail.

## 5. Where things go

| You want to… | Change |
| --- | --- |
| Add an HTTP page or form | `app/api/routes/` + `templates/` |
| Add a business use case | `app/services/` or the relevant package (`translation/`, `billing/`, …) |
| Add a PocketBase collection accessor | `app/repositories/` |
| Add a document format adapter | `app/documents/adapters/` + parser/exporter |
| Add a provider protocol | `app/providers/` (one adapter; reuse the engine) |
| Make a collection editable in admin | `app/admin/registry.py` (data, not handlers) |
| Change what the app does by default | `seeds/` or `system_settings` — not code |

## 6. Documentation

- User-facing or architectural change? Update the relevant doc under `docs/`.
  Start from the [documentation index](docs/README.md).
- Significant, hard-to-reverse decision? Add an
  [ADR](docs/decisions/) (context, decision, consequences).
- Keep terminology consistent with the index’s terminology table.

## 7. Tests

Tests are **hermetic** — never require a live PocketBase; mock upstream HTTP.
Add the smallest test that fails if the behaviour breaks. See
[Testing](docs/testing.md) for layout, fixtures and enforced invariants.

## 8. Commits and pull requests

- Keep commits focused and their messages explanatory.
- Do not commit generated assets, `.env`, `var/`, or credentials.
- In a pull request, describe the behaviour change, the tests, and any docs
  updated. Call out deliberate limitations and unresolved conflicts rather than
  hiding them.

## 9. License

Book Fork is MIT-licensed. By contributing you agree your contribution is
licensed under the same terms.
