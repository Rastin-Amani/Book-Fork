# Book Fork — Testing

> **Verification status.** Structure and commands verified against
> `pyproject.toml` (`[tool.pytest.ini_options]`), `tests/conftest.py`,
> `tests/fakes.py` and the test tree.

---

## 1. Running the tests

```bash
uv run pytest            # whole suite
uv run pytest tests/unit # unit tests only
uv run pytest tests/integration
uv run pytest -k billing # by keyword
```

`pytest` is configured with `testpaths = ["tests"]`, `asyncio_mode = "auto"`
(async tests need no decorator), `addopts = "-q"`, and `filterwarnings = ["error"]`
— warnings fail the suite except two documented ignores (Starlette's TestClient
deprecation and pysbd's import-time `SyntaxWarning`).

Current size: **62 unit test modules** and **4 integration modules** (~427 test
functions).

## 2. Hermetic by design

Tests **never require a live PocketBase**. `tests/conftest.py` sets the required
secrets, forces `APP_ENV=test`, and provides:

- `fake_pb` — an in-memory `FakePocketBase` (`tests/fakes.py`).
- `pb` — a `PocketBaseClient` bound to fake transport.
- `settings` — `Settings` with a temporary local storage root.
- `app` — the real FastAPI app built with test settings.
- `client` — a Starlette `TestClient` context.

Upstream HTTP is mocked with `httpx.MockTransport`. Integration tests exercise
the real routes, middleware, CSRF and HTMX rendering against fakes.

## 3. Layout

### `tests/unit/`

Focused, dependency-light tests of a single module or service. Groups include:

- **Config & auth:** `test_config`, `test_crypto`, `test_csrf`,
  `test_ratelimit`, `test_security_headers`, `test_urls`, `test_ssrf_matrix`,
  `test_configure_auth`.
- **Repositories & PocketBase:** `test_repositories`, `test_pocketbase_client`,
  `test_push_schema`, `test_storage`, `test_storage_download`.
- **Documents:** `test_document_engine`, `test_document_model`,
  `test_document_safety`, `test_epub`, `test_pdf`, `test_book_export`,
  `test_segmentation`, `test_placeholders`, `test_ocr`, `test_multilingual_fixtures`.
- **Languages:** `test_language_registry`, `test_language_detector`,
  `test_language_normalize`.
- **Translation:** `test_translation_engine`, `test_translation_context`,
  `test_translation_glossary`, `test_translation_memory`,
  `test_translation_normalization`, `test_translation_structured`,
  `test_translation_validation`, `test_policy`, `test_translation_policy_engine`,
  `test_prompt_renderer`, `test_model_routing`.
- **Providers:** `test_provider_factory`, `test_provider_runtime_ssrf`,
  `test_provider_testing`, `test_provider_errors`,
  `test_provider_credentials`, `test_translation_provider_openai`.
- **Billing:** `test_billing_pricing`, `test_billing_estimation`.
- **Worker/jobs:** `test_jobs_service`, `test_worker_runner`,
  `test_worker_executor`, `test_worker_store`, `test_worker_heartbeat`,
  `test_worker_registry`, `test_entrypoint`.
- **Services & platform:** `test_limits_service`, `test_retention_service`,
  `test_settings_service`, `test_seed`, `test_metrics`, `test_cache`,
  `test_error_codes`, `test_workspace_authz`, `test_workspace_service`.

### `tests/integration/`

End-to-end behaviour through the HTTP layer:

- `test_web.py` — pages, auth flow, CSRF enforcement, HTMX partials, access
  control (including cross-workspace 404s).
- `test_ui_app.py` — authenticated app pages and mutations.
- `test_admin.py` — admin gating and CRUD.
- `test_e2e_flow.py` — the full upload → translate → download journey.

## 4. Fixtures and fakes

- `tests/fakes.py` — `FakePocketBase`, an in-memory stand-in for the PocketBase
  REST API used by the client and repository tests.
- `tests/documents_fixtures.py`, `tests/translation_fixtures.py`,
  `tests/job_fixtures.py` — sample documents, segments and jobs.

Use these instead of adding real network calls to tests.

## 5. What to test

The suite doubles as an executable specification. Notable enforced invariants:

- **No hardcoded business defaults.** Seeds contain no credentials (asserted by
  `test_seed`).
- **Stable error codes.** `test_error_codes` guards the taxonomy in
  `app/exceptions.py`.
- **Cross-workspace isolation.** Integration tests assert 404 on foreign ids.
- **CSRF on every mutation.** Integration tests assert rejection without a token.
- **SSRF matrix.** `test_ssrf_matrix` covers IPv4/IPv6, IPv4-mapped IPv6,
  credentials-in-URL, schemes and metadata addresses.

When adding behaviour, add the smallest test that fails if the invariant breaks.
Keep new tests hermetic — no live services.

## 6. Quality gates

Before committing, run the full gate (also available as `make check`):

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

- **Ruff** enforces style plus a security lint set (`S`, `ASYNC`, `B`, `SIM`,
  `UP`, `RUF`). `assert` is allowed; `print` is banned outside `tests/` and
  `scripts/`.
- **mypy** runs in strict mode; a few third-party/untyped document-adapter
  modules have explicit, narrow overrides in `pyproject.toml`.
