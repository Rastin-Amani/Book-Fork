# Book Fork — FAQ

Short answers, each traceable to the implementation. For depth, follow the links.

---

**What is Book Fork?**

A multilingual document-translation service that translates EPUB and PDF files
between arbitrary language pairs using a configurable LLM provider. See the
[User Guide](user-guide.md) and [Architecture](architecture.md).

---

**Which input formats are supported?**

**EPUB and PDF only.** The upload intake sniffs content and rejects everything
else. The seeded `upload.allowed_extensions` list mentions `txt` and `docx`, but
the ingestion path does not accept them.

---

**What outputs do I get?**

Each finished job produces downloadable book files. The default is **PDF and
EPUB** (`DOCUMENT_OUTPUT_FORMATS=epub,pdf`), independent of the source format.
An unavailable format is skipped, not fatal.

---

**Can I translate between any two languages?**

Yes. Languages come from the registry, not code. The seed ships 60 languages;
direction (LTR/RTL) and script are derived from CLDR data. See
[Data model](data-model.md).

---

**Do I have to use Book Fork's own AI?**

No. Use **Book Fork-managed** connections (spend credits) or connect **your own**
OpenAI-compatible endpoint (billed by your provider, zero Book Fork credits).
The mode is a per-connection setting.

---

**Which providers can I connect?**

Any OpenAI-compatible chat-completions endpoint. The seed catalog also lists
Anthropic, Google Gemini, Ollama (self-hosted) and Custom endpoint records; the
generic adapter covers OpenAI-compatible gateways, Ollama, vLLM and similar.
Adding a distinct protocol later is one adapter — the engine is untouched.

---

**Are my API keys safe?**

Keys are encrypted at rest with Fernet (`ENCRYPTION_KEY`), stored in a
superuser-only `provider_credentials` collection, decrypted only to build a
client, never logged, and never shown again or returned in any response.

---

**Is my document content sent anywhere?**

It is sent to the provider selected for the job (managed or your own). Book Fork
itself never logs document bodies or prompts. Raw LLM responses are **not**
retained by default (`providers.raw_response_retention=false`).

---

**Why is my job stuck at “queued”?**

Translation runs in a separate worker process. If no worker is running, jobs stay
queued. Check `/health/worker`. See
[Troubleshooting](troubleshooting.md#a-jobs).

---

**Can I edit translations before downloading?**

Yes. Open **Review segments** on a job, edit the translation, **Save**, and tick
**Approved** to mark a segment validated. Regeneration and “add glossary term”
actions are not yet implemented.

---

**Why isn't my glossary being used?**

The glossary UI stores terms, but the current UI does not yet expose attaching a
glossary to a job or profile. This is a known limitation, not a bug in your
terms.

---

**Do I get charged for reused translations?**

Reusing an **approved** translation-memory entry makes no provider call and costs
no credits. New pairs are stored but not auto-approved; only approved entries are
reused, and always per exact language pair.

---

**How do credits work?**

Managed jobs estimate → **reserve** → translate → **settle** (charge actual) →
**refund** unused. The ledger is append-only and reference-guarded
(`job:<id>:reserve`), so a crash cannot double-charge. Own-API jobs cost zero
Book Fork credits. See [Billing & credits](billing.md).

---

**Can I buy credits in the app?**

Not currently. Purchasing/crediting is an administrative action
(`/admin/credit-wallets/{id}/adjust`). There is no self-service checkout UI.

---

**Do I need to verify my email?**

No. Verification is available but the application does not require it before use.

---

**Password-reset email never arrived — why?**

Book Fork delegates reset and verification emails to **PocketBase**. If
PocketBase has no mailer configured, the request still succeeds but no email is
sent. Configure PocketBase's SMTP mailer. See
[Troubleshooting](troubleshooting.md#d-accounts-and-sessions).

---

**Can several people share a workspace?**

Workspaces, members and roles (`owner`, `admin`, `member`, `viewer`) are modelled
and enforced in data, but the current UI creates only your **personal**
workspace; there is no invitation flow yet.

---

**How do I make someone an administrator?**

Add their email to the `admin.emails` system setting. They can then reach
`/admin`. Admin queries also require `POCKETBASE_SERVICE_CREDENTIAL`. See the
[Admin Guide](admin-guide.md).

---

**Can I change the prompts, models, prices or limits?**

Yes — all are configuration records, not code: prompts (versioned), models,
capabilities, pricing, credit pricing, limits and retention. See
[Configuration](configuration.md) and the [Admin Guide](admin-guide.md).

---

**Does it need Redis or a message queue?**

No. The durable worker claims jobs from PocketBase with leases and bounded
concurrency. No Redis is required.

---

**Is there a REST API I can build on?**

Not really — Book Fork is a server-rendered app. The JSON surface is
`GET /api/me`, the health endpoints and `/metrics`, plus interactive OpenAPI docs
in non-production. See the [API Reference](api-reference.md).

---

**Where do I start if I want to contribute?**

See [Contributing](../CONTRIBUTING.md), [Development](development.md) and
[Testing](testing.md).
