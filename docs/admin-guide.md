# Book Fork — Admin Guide

This guide is for administrators who configure and operate Book Fork: enabling
the admin area, managing configuration records, curating prompts and models,
pricing managed books, and overseeing jobs and workers.

> **Verification status.** Every route, resource slug, field and action below was
> checked against `app/api/routes/admin.py`, `app/admin/registry.py`, the admin
> templates and the repository layer. Resource fields are data — if the registry
> changes, the UI changes with it.

---

## 1. Becoming an administrator

Admin access is controlled by the **`admin.emails`** system setting — a JSON list
of email addresses. A signed-in user whose email is in that list may open
`/admin/*`; anyone else receives **403 Administrator access required.**

Admin routes additionally require the **PocketBase service credential**
(`POCKETBASE_SERVICE_CREDENTIAL`). Without it, admin pages fail with a
configuration error. The service credential is a superuser token or
`identity:password`, and admin queries run with it so they can see across all
workspaces.

> **Note on bootstrap.** `admin.emails` is seeded as an empty list. Add your
> address before those users can reach `/admin`. This is normally done through
> the PocketBase Dashboard or the seed data before first use.

---

## 2. The admin area

The hub is at **`/admin`**. Resources are grouped into categories:

**Access**
- `users` — accounts (read-only creation; created through signup).
- `workspaces` — name, slug, owner, plan.
- `workspace-members` — workspace ↔ user links with role
  (`owner | admin | member | viewer`).

**Content**
- `documents` — inspect/remove uploaded sources (no creation).
- `translation-jobs` — inspect jobs; edit status/quality/error fields.
- `failed-jobs` — jobs with status `failed` or `cancelled`.
- `job-events` — the structured job log (read-only; level editable).

**Providers & models** (`/admin/providers`, `/admin/models`,
`/admin/model-capabilities`, `/admin/provider-connections`)
- `providers` — protocol catalog records.
- `provider-connections` — per-workspace connections (credentials never shown).
- `models` — identifier, context window, limits, prices, quality.
- `model-capabilities` — per (model, source, target) support/preference/quality.

**Prompts & profiles**
- `prompt-templates` — with a **new-version** action.
- `prompt-versions` — with **activate**, **archive**, **compare** actions.
- `translation-profiles` — quality mode, prompt template, temperature, batch size,
  segmentation, etc.

**Languages**
- `languages` — BCP-47 code, name, native name, direction, script, locale.
- `language-variants` — per-locale normalization/segmentation behaviour.

**Glossaries & memory**
- `glossaries`, `glossary-terms`, `translation-memory`.

**System**
- `system-settings` — typed business defaults (create allowed, delete blocked).
- `workers` — worker heartbeats (read-only).

Special pages:
- `/admin/metrics` — the in-process counter/gauge snapshot.
- `/admin/prompt-versions/compare` — side-by-side prompt version diff.

---

## 3. Generic CRUD behaviour

For most resources the admin area provides list → new → edit → delete:

| Operation | Route | Notes |
| --- | --- | --- |
| List | `GET /admin/{slug}` | Up to 200 records, resource-defined sort/filter. |
| New form | `GET /admin/{slug}/new` | Only when `can_create`. |
| Create | `POST /admin/{slug}` | CSRF required. |
| Edit form | `GET /admin/{slug}/{id}/edit` | |
| Update | `POST /admin/{slug}/{id}` | CSRF required; only when `can_update`. |
| Delete | `POST /admin/{slug}/{id}/delete` | CSRF required; only when `can_delete`. |

Field types map directly to inputs: `text`, `textarea`, `int`, `float`, `bool`,
`json`, `select` (with fixed choices), `relation` (a dropdown of related records)
and `readonly`. JSON fields are validated; an invalid JSON body returns **422**
with the message *“{label} must be valid JSON.”*

Relation fields list up to 500 target records and are labelled by the target
resource's label field.

---

## 4. Prompts and prompt versioning

Prompt templates are versioned so editing a prompt never changes a running or
finished job (jobs reference an exact `prompt_version`).

To change a prompt:

1. Go to `/admin/prompt-templates`.
2. Open a template and choose **new-version**.
3. Write the new **Body**; the next version number is suggested automatically.
4. Choose **Create** (status defaults to `draft`).
5. On `/admin/prompt-versions`, choose **activate** on the version you want. This
   activates it and archives its siblings in the same template.
6. Use **archive** to retire a version, or **compare** to review two versions
   side by side.

Prompt bodies are rendered by a sandboxed renderer with an allow-list of
variables (`source_language`, `target_language`, `source_segments`, glossary,
memory, style/tone/domain, …). Unknown or unsafe expressions fail rather than
execute.

---

## 5. Providers, models and capabilities

Routing is entirely data-driven — there is no model-specific code.

1. **Providers** (`/admin/providers`): ensure a protocol record exists. The
   seed catalog includes OpenAI-compatible, Anthropic, Google Gemini, Ollama
   (self-hosted) and Custom endpoint records, but **only `openai_compatible`
   and `ollama` have adapters implemented** (`app/providers/factory.py`). A
   connection whose protocol has no adapter fails with `unsupported_protocol`.
   Add an adapter before enabling the others.
2. **Models** (`/admin/models`): add the model identifier, context window, output
   limits, structured/vision/temperature support, and generic pricing
   (`input_cost_per_million_tokens`, `output_cost_per_million_tokens`, optional
   `request_cost`), plus a `quality_score`.
3. **Model capabilities** (`/admin/model-capabilities`): declare whether a model
   `supported` and `preferred` for each (source, target) language pair, with a
   quality score. This is how a model can be strong for one pair and weak for
   another.
4. **Provider connections** (`/admin/provider-connections`): per-workspace
   connections with `billing_mode` (`managed` or `own_api`). User API keys live
   in the server-only `provider_credentials` collection and are **never shown**.

Quality modes (`best`, `balanced`, `quality`, `fast`, `economy`) rank candidate
models by capability/quality and cost; no tier embeds a model name.

---

## 6. Languages

`languages` and `language-variants` are data. Direction (`ltr`/`rtl`), script,
locale and the normalization/segmentation behaviour are read from records and
CLDR, never from Python lists. Add a language by creating a record with its
BCP-47 code; leave name/script/direction to CLDR defaults or override them.

---

## 7. Book pricing and orders

There is no customer credit wallet. A managed job is a book order priced at
**$7 flat up to 1,000 pages**, plus **$7 per extra 1,000-page block**. The order
snapshot is stored on the job (`metadata.order`) and shown on the customer's
billing page at `/app/settings/billing`.

Operators reconcile orders through their payment provider or invoice system.
Failed and cancelled jobs are not charged. Pricing is configured with
`billing.book_price_usd`, `billing.pages_per_block` and
`billing.words_per_page`; provider cost is still recorded on each job for margin
monitoring.

---

## 8. System settings

`system-settings` holds typed business defaults. Value types are
`string | int | float | bool | json`. Deleting settings is disabled; create or
edit instead. Key groups include:

- `upload.*` — maximum file size and allowed extensions.
- `jobs.*` and `worker.*` — concurrency, lease, heartbeat, poll and retries.
- `translation.*` — batch size, context, prompts, profiles, detection threshold.
- `billing.*` — book price, pages per block, words per page, currency.
- `limits.*` — uploads/day, jobs/day, concurrent jobs, retries per job
  (0 = unlimited).
- `retention.*` — automatic deletion windows (0 = keep).
- `admin.emails` — the admin allow-list.
- `providers.raw_response_retention` — whether raw LLM responses are retained
  (default: **false**).

The authoritative seeded defaults are in
[`../seeds/system_settings.json`](../seeds/system_settings.json); the
user-facing reference is [Configuration](configuration.md).

---

## 9. Workers and metrics

- `/admin/workers` lists worker records: `worker_id`, host, status, current jobs
  and last heartbeat.
- `GET /health/worker` returns 200 when at least one worker heartbeated within
  the last **180 seconds**, otherwise 503.
- `/admin/metrics` and `GET /metrics` expose lightweight per-process counters and
  gauges. These are **not aggregated across replicas**; sum at scrape time.

---

## 10. Operational responsibilities

The admin is also the operator in a self-hosted deployment. Common tasks:

- **Seed reference data** after provisioning (idempotent):
  `uv run python scripts/seed.py`.
- **Push schema** to a PocketBase that cannot run migrations:
  `uv run python scripts/push_schema.py …`.
- **Run retention** on a schedule:
  `uv run python scripts/retention.py`.
- **Back up** PocketBase data, seeds and object storage together.

These are covered in detail in the [Operations Runbook](operations.md) and
[Deployment](deployment.md).
