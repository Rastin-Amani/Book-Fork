# Data model & configuration engine

Phase 2 makes Book Fork configuration-driven: languages, providers, models, prompts,
profiles, capabilities, glossaries, memory, credits and settings are **records**,
not Python constants.

Schema is defined by reproducible PocketBase migrations in `pb_migrations/` and
populated by idempotent seeds in `seeds/`.

## Ownership model

Every user-owned object belongs to a **workspace**. `workspaces` and
`workspace_members` are the tenancy boundary:

- `workspaces.owner` is a relation to `users`.
- `workspace_members` links `workspace` ↔ `user` with a `role`
  (`owner | admin | member | viewer`).

PocketBase rules enforce isolation using back-relation filters, e.g.:

```
workspace.workspace_members_via_workspace.user ?= @request.auth.id
```

Documents, sections, jobs, segments, attempts, events, glossaries, connections,
wallets and usage are all gated by that expression (directly or through their
parent). The application additionally enforces ownership in
`app/workspaces/authz.py` (`WorkspaceAccess`). This is defense in depth: UI
visibility is never authorization.

`provider_credentials` is server-only (`listRule=null`): API keys are stored
encrypted and never readable through the public API.

## Collections

### Tenancy & identity
`users` (built-in, rules normalized), `workspaces`, `workspace_members`.

### Language registry (language-agnostic)
- `languages` — `language_code` (BCP-47), ISO 639-1/639-3, `name`, `native_name`,
  `script_code`, `direction`, `default_locale`, `enabled`, `popular`,
  `sort_order`, `metadata`.
- `language_variants` — per-locale metadata plus the configurable behaviour
  profiles: `normalization_pipeline`, `segmentation_strategy`,
  `punctuation_profile`, `quotation_profile`, `formatting_profile`.

Direction is **data**. There is no RTL/LTR list in Python; it is derived from
CLDR (`app/language/normalize.py`) and overridable per record.

### Documents
`documents` (metadata incl. optional `source_language` until detection,
`detected_language`, `storage_key`, `status`) and `document_sections`
(hierarchical structure, self-referencing `parent`).

### Translation
- `translation_jobs` — languages, profile/connection/model/prompt_version
  references, `status`, progress counters, reserved/actual credits, lease fields
  (`worker_id`, `lease_id`, `lease_expires_at`, `last_heartbeat`), errors, and a
  `snapshot` JSON capturing the resolved configuration.
- `translation_segments` — stable segment ids, source/target text, block type,
  per-segment token/cost counters, `attempt_count`.
- `translation_attempts` — append-only per attempt: provider/model/prompt
  references, timings, tokens, cost, validation status, `response_metadata`.
  Raw-response retention is controlled by the `providers.raw_response_retention`
  setting; the default is privacy-conscious (metadata only).
- `job_events` — structured job log.

### Prompts
`prompt_templates` + versioned `prompt_versions` (`status`: draft/active/archived).
Jobs reference the exact `prompt_version`, so editing a prompt never changes an
existing job.

### Providers & models
- `providers` — protocol catalog (`provider_type`: openai_compatible, anthropic,
  gemini, ollama, custom). Code contains adapters; providers are records.
- `provider_connections` — per-workspace endpoint/config.
- `provider_credentials` — encrypted secret (server-only).
- `provider_models` — identifier, context window, token limits, prices, quality.
- `model_capabilities` — per (model, source_language, target_language) with
  `supported`, `preferred`, `quality_score`. This is how a model can be strong
  for German→Japanese and weak for Japanese→Persian.

Pricing is data (`input_cost_per_million_tokens`, ...), never Python constants.

### Profiles
`translation_profiles` — style/tone/domain, quality mode, prompt template,
glossary ids, segmentation/context/normalization/validation config, temperature,
batch size. System defaults have `is_system_default=true`; workspace profiles are
owned by a workspace.

### Knowledge
- `glossaries` + `glossary_terms` — always language-pair scoped
  (`source_language`, `target_language`), with `preferred`/`forbidden`.
- `translation_memory_entries` — exact-match lookup scoped by language pair
  (never by source hash alone).

### Billing
- `credit_wallets` — cached running `balance` per workspace/currency.
- `credit_transactions` — the audit trail and source of truth:
  `purchase | bonus | reservation | consumption | refund | adjustment |
  expiration`, with `balance_before`, `amount`, `balance_after`, `job`,
  `reference` (idempotency).
- `usage_events` — token/cost/credit usage per workspace.

### Configuration
`system_settings` — typed (`string | int | float | bool | json`) key/value records
with `category`, `description`, `editable`.

## Configuration resolution

`app/translation/policy.py` (`TranslationPolicyService`) is the single policy
boundary. Given a source/target pair, quality mode, workspace and optional
preferred connection it resolves: profile → provider connection → model (via
`model_capabilities`, preferring `preferred`/higher quality) → active prompt
version → segmentation/normalization/validation config, and returns a snapshot.
There is no scattered `if/elif` provider logic.

Prompt bodies are rendered by `app/prompts/renderer.py` with a Jinja2 sandbox and
an allow-list of variables (`source_language`, `glossary`, `source_segments`, …).
`eval`/unsafe attribute access are impossible.

## Seeds

`seeds/*.json` are data (languages, system settings, profiles, prompt templates,
provider catalog). `app/services/seed.py` applies them through the repository
layer and is idempotent: records are matched by natural key
(`language_code`/`key`/`slug`/`name`) and updated, not duplicated. Prompt bodies
that change produce a **new version** and archive the previous one.

Seeds contain **no credentials** (enforced by a test).

## Migrations & remote schema sync

- Local/self-hosted: PocketBase applies `pb_migrations/` on serve
  (`--migrationsDir=./pb_migrations`).
- Remote instances that cannot run migrations are synced with
  `scripts/push_schema.py`, which recreates the schema through the Admin API
  (dependency-ordered create, then a second pass restoring self-relations and
  API rules).

## Repository layer

`app/repositories/base.py` provides a typed generic
`PocketBaseRepository[M]`; concrete repositories exist for every collection
(`languages`, `documents`, `translation`, `providers`, `prompts`, `knowledge`,
`billing`, `settings`, `workspaces`). Filter values are escaped to prevent
filter injection. Business services depend on repositories, never on raw
PocketBase calls.
