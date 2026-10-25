# Book Fork Documentation

Start here. This index maps every document by the reader it serves and the
question it answers.

---

## By audience

### I want to use Book Fork

- [User Guide](user-guide.md) — create an account, translate a document, review,
  download, providers, glossaries, memory, billing.
- [FAQ](faq.md) — short answers to common questions.
- [Troubleshooting](troubleshooting.md) — symptom → cause → fix.

### I run or administer Book Fork

- [Admin Guide](admin-guide.md) — the `/admin` area: resources, prompts, models,
  languages, pricing, settings.
- [Operations Runbook](operations.md) — services, health, scaling, retention,
  backups, upgrades, incidents.
- [Deployment](deployment.md) — containers, topology, reverse proxy, environment.
- [Configuration](configuration.md) — environment variables and system settings.
- [Security audit](security-audit.md) — verified controls and known limitations.

### I want to understand how it works

- [Architecture](architecture.md) — principles, layering, request lifecycle,
  stack and versions.
- [Data model & configuration engine](data-model.md) — collections, ownership,
  policy resolution, seeds and migrations.
- [Document engine](documents.md) — canonical model, EPUB/PDF, segmentation,
  placeholders, book output, fonts, safety.
- [Translation engine](translation.md) — plan, policy engine, providers,
  structured output, context, memory, glossary, validation.
- [Durable worker](worker.md) — lifecycle, leases, execution pipeline, retries,
  cancellation, idempotency.
- [Providers, routing & billing](providers-and-billing.md) — modes, adapters,
  credential security, SSRF, capability routing, book orders.
- [Product UI & UX](ui.md) — routes, shell, new-translation workflow, job page,
  RTL, accessibility.
- [Design system](../DESIGN.md) — the “Warm Paper Workspace” visual system.

### I want to develop or contribute

- [Contributing](../CONTRIBUTING.md) — setup, workflow, quality gates, PR
  expectations.
- [Development](development.md) — prerequisites, commands, PocketBase, seeding.
- [Testing](testing.md) — test layout, fixtures, invariants, quality gates.
- [Architecture Decision Records](decisions/README.md) — the recorded “why” for
  each phase.
- [Changelog](../CHANGELOG.md) — what shipped, by phase.

### Short canonical references

These are deliberately brief; each points at the deep document:

- [Providers](providers.md) · [Billing](billing.md) ·
  [Document engine reference](document-engine.md) ·
  [Translation engine reference](translation-engine.md).

---

## Terminology

Keep these terms consistent when writing about Book Fork:

| Term | Meaning |
| --- | --- |
| **Workspace** | The tenancy boundary that owns documents, jobs, glossaries and connections. Every user gets a personal workspace. |
| **Document** | An uploaded, immutable EPUB/PDF source. |
| **Translation job** | A queued/running/finished unit of work translating a document to one target language. |
| **Segment** | A translatable unit within a job (paragraph or sentence). |
| **Attempt** | One append-only provider call for a segment. |
| **Plan / snapshot** | The immutable resolved configuration a job executes. |
| **Provider** | A protocol catalog record (e.g. OpenAI-compatible). |
| **Provider connection** | A per-workspace endpoint + auth + billing mode. |
| **Billing mode** | `managed` ($7 book order) or `own_api` (user's provider, free). |
| **Book order** | One flat-priced managed job; stored on the job snapshot. |
| **Profile** | A translation profile: quality mode, prompt, temperature, segmentation, context. |
| **Quality mode** | `best` · `balanced` · `quality` · `fast` · `economy` — routing tiers, not model names. |
| **Glossary** | Language-pair-scoped preferred/forbidden terminology. |
| **Translation memory** | Approved exact source→translation pairs, reused without a provider call. |
| **Worker** | The separate process that executes jobs. |
| **Lease** | The claim a worker holds on a job, refreshed by heartbeat. |

---

## Documentation status

All documents describe the implementation at the **Phase 8 complete** state. Where
behaviour is uncertain or a conflict exists, the document says so explicitly
rather than stating an assumption as fact. Notable open items are listed in the
[User Guide “Current limitations”](user-guide.md#13-current-limitations-verified)
and the [Troubleshooting](troubleshooting.md) entries.
