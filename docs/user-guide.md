# Book Fork — User Guide

This guide is for people who use Book Fork to translate documents. It covers
creating an account, translating an EPUB or PDF, reviewing the result,
downloading it, and managing your provider connections, glossaries, translation
memory and billing.

> **Verification status.** Every screen name, button label and behaviour below
> was checked against the current implementation (routes in `app/api/routes/`,
> templates in `templates/`, and services in `app/`). Where behaviour is not
> obvious from the code it is marked as observed or as a current limitation.

---

## 1. What Book Fork does

Book Fork translates **EPUB and PDF documents between arbitrary source and target
languages** using a configurable large-language-model (LLM) provider. You can
either:

- let Book Fork use a **managed** provider and pay **$7 per book** (up to
  1,000 pages), or
- connect **your own** OpenAI-compatible API and use Book Fork free, paying that
  provider directly.

Every finished translation produces downloadable book files (PDF and EPUB by
default) regardless of the source format.

---

## 2. Create an account and log in

Sign-in and sign-up are the same action, using **Google** or **GitHub**. There
are no passwords: the first sign-in creates your account (PocketBase links an
existing record by verified email), and every later sign-in uses the same
provider.

### Sign in for the first time

1. Open `/login` (or choose **Start translating free** on the marketing site).
2. Choose **Continue with Google** or **Continue with GitHub**.
3. Approve the provider's request. Book Fork receives only your name, email
   address and profile picture.
4. You land on your dashboard (`/app`). Your personal workspace is created on
   first use.

`/signup` redirects to the same page, so there is nothing separate to fill in.

### Sign in again

Go to `/login` and choose the same provider. If you are already signed in,
`/login` sends you straight to `/app`.

### Log out

Use the account menu in the top bar and choose **Log out**. The session cookie is
cleared.

### Recovering access

There is no password to reset. If a provider account is lost, sign in with the
other provider using the same verified email, or contact an administrator. A
deactivated account cannot sign in.

> **Note.** If the page says **“Sign-in is not configured yet.”**, an
> administrator still has to enable Google/GitHub in PocketBase. See
> [Development](development.md) and [Troubleshooting](troubleshooting.md).

---

## 3. The dashboard and navigation

After logging in you land on the dashboard (`/app`). It shows:

- **Active jobs**, **Completed**, **Documents** and **Managed book** price
  summary cards.
- A **Recent translations** table with the language pair, a status badge, a
  progress bar and an **Open** link.
- A **Quick start** panel: *Translate a document*, *Connect a provider*,
  *Create a glossary*, *Browse memory*.
- A short **Documents** list.

The top navigation is: **Dashboard**, **Translations**, **Documents**,
**Glossaries**, **Memory**, **Providers**. The dark **New translation** button is
in the top bar on every app page.

> **Tip.** Internal navigation is HTMX-driven: the page shell stays put and only
> the content area changes. This is expected.

---

## 4. Translate a document

Choose **New translation** (top bar) or go to `/app/translations/new`. The form
has three steps and then an estimate.

### Step 1 — Document

Pick exactly one source:

- **Upload EPUB or PDF** — choose a `.epub` or `.pdf` file, **or**
- **…or use an existing document** — select a previously uploaded document.

Only **EPUB and PDF** are accepted. The file must be within the configured
maximum upload size (default **100 MiB / 104,857,600 bytes**, set by the
`upload.maximum_file_size` system setting).

### Step 2 — Languages

- **Source language** — choose a language or **Auto-detect**. With Auto-detect,
  Book Fork reads a sample of the document, detects the language at job-creation
  time, and saves it on the document.
- **Target language** — required. The list comes from the language registry and
  shows native names and direction.

### Step 3 — Provider & quality

- **Provider** — **Auto (Book Fork)** for a managed book, or one of your
  connections (marked *(your API)* when it is your own key).
- **Profile** — **Auto**, or a specific translation profile (for example
  *Default Translation*, *Fast Draft*, *Literary Quality*).
- **Quality** — **Auto**, **Best**, **Balanced**, **Economy** or **Fast**.
  (Quality mode is a routing tier, not a model name.)
- **Save translations to memory for reuse** — optional checkbox.

### Estimate

Choose **Estimate** to see a server-rendered estimate card:

- **Source words** and **estimated pages** (approximate).
- The resolved **Provider** and **Model**.
- Either the flat **book price** (managed) or a **Your own API** badge stating
  *“Free with your key — no Book Fork charge.”*

Estimates are approximate and labelled as such.

### Start

Choose **Start translation**. Book Fork creates the job, stores the resolved
configuration as a snapshot, and queues it. You are redirected to the job page.

> **Important.** Translation runs in a **separate worker process**. If no worker
> is running, jobs stay **queued** and never progress. The estimate and job
> creation succeed without a worker, but translation does not.

---

## 5. Watch and control a translation

The job page (`/app/translations/{id}`) shows the document name, the language
pair, and the resolved model. The status panel refreshes every **2 seconds while
the job is active**, and shows:

- a **status badge**;
- `completed/total segments`, plus a **failed** count when any segment failed;
- a **percentage** and progress bar;
- an **error message** when the job failed.

The possible job statuses are:

`queued → preparing → parsing → segmenting → translating → finalizing →
completed`, plus `failed`, `cancelling` and `cancelled`.

Available actions depend on state:

| Action | When it is shown |
| --- | --- |
| **Cancel** | While the job is active. Cooperative — the worker refunds the reservation and finishes as `cancelled`. |
| **Retry failed** | When the job status is `failed`. Retranslates only the failed segments. |
| **Download PDF** / **Download EPUB** | When output exists. |
| **Review segments** | Always (segments appear as they are produced). |

Progress and status come from the server; they are never simulated.

---

## 6. Review and edit translations

Open **Review segments** (or `/app/translations/{id}/review`). Each segment shows
an **Original** panel and a **Translation** panel:

1. Edit the text in the **Translation** box.
2. Choose **Save** to store the edited translation.
3. Tick **Approved** (then **Save**) to mark the segment `validated`.

A segment that is `validated` shows a green **validated** marker; otherwise its
raw status is shown.

> **Current limitation.** Regenerate and “add glossary term” actions are not yet
> present. Approving a segment does not automatically add it to translation
> memory.

---

## 7. Download the result

When the job completes, the status panel offers **Download PDF** and **Download
EPUB** (formats are configured by `DOCUMENT_OUTPUT_FORMATS`; unavailable formats
are skipped). The downloaded file is named after the document with the target
language appended, for example `mybook-fa.epub`.

You can always download the original source from the document page
(`/app/documents/{id}` → **Download source**).

---

## 8. Documents

The **Documents** page (`/app/documents`) lists your uploaded sources with type,
size and source language. Open a document to see:

- **Type**, **Size**, **Source language**, **Detected** language and **Filename**;
- **Download source**;
- **Translate** (jumps to the new-translation form with that document selected).

Documents are immutable sources — uploading the same file again creates a new
document.

---

## 9. Providers (bring your own model)

Open **Providers** (`/app/providers`) to connect your own OpenAI-compatible
endpoint. Choose **Add provider** and fill in:

- **Name** — a label for this connection.
- **Protocol** — the provider type from the catalog. **Only
  OpenAI-compatible and Ollama (self-hosted) currently have adapters.** The
  catalog also lists Anthropic, Google Gemini and Custom endpoint records, but
  selecting one fails the connection test with `unsupported_protocol` until an
  adapter is added. An Anthropic or Gemini endpoint can still be used if it is
  reachable through an OpenAI-compatible gateway (choose *OpenAI-compatible*
  and point the base URL at it).
- **Base URL** — the endpoint, e.g. `https://api.example.com/v1`.
- **API key** — encrypted at rest and **never shown again** after saving.
- **Default model** — e.g. `gpt-4o-mini`.
- **Billing** — *My own API — free* or *Book Fork-managed — $7 per book*.

Each row offers:

- **Test** — a safe connection diagnostic. Possible outcomes: `connected`,
  `authentication_failed`, `model_unavailable`, `endpoint_unreachable`,
  `unsupported_protocol`, `unsafe_url`. The API key is never returned.
- **Enable** / **Disable**.
- **Delete** (confirms first).

> **Note.** A private/self-hosted endpoint (for example local Ollama) is only
> permitted when the connection is explicitly allowed to use private addresses.
> Public endpoints that resolve to private or metadata addresses are rejected to
> protect the server. See [Security audit](security-audit.md).

---

## 10. Glossaries

Glossaries hold language-pair-specific terminology.

1. Open **Glossaries** → **Create a glossary** (`/app/glossaries/new`).
2. Enter a **Name** and optional **Description**, then **Create glossary**.
3. On the glossary page, use **Add a term** to add:
   - **Source language** and **Target language** (language tags such as `en`,
     `fa`);
   - **Source term** and **Target term**;
   - optional **Preferred** and **Forbidden** flags.
4. Terms can be deleted individually.

> **Current limitation.** Glossary creation and term management are complete, but
> the UI does not yet expose attaching a glossary to a translation job or
> profile. The translation engine already supports glossaries through the profile
> configuration; wiring an attachment control into the UI is a follow-up. Do not
> assume terms automatically affect a job until that control exists.

---

## 11. Translation memory

**Memory** (`/app/translation-memory`) is a read-only list of approved
source→translation pairs Book Fork can reuse across jobs. Reusing a pair causes
**no provider call and no charge**.

- Tick **Save translations to memory for reuse** on the new-translation form and
  new pairs are stored, but they are **not auto-approved**.
- Only **approved** entries are reused.
- Memory is always scoped to the exact language pair.

Approval currently happens in the admin area (see the
[Admin Guide](admin-guide.md)); a user-facing approval control is not present.

---

## 12. Settings and billing

**Settings** (`/app/settings`) links to:

- **Languages** — the registry with direction, script and native names.
- **Translation profiles** — quality mode and segmentation strategy per profile,
  and whether it is a system default.
- **Billing** — per-book pricing and your orders.
- **Providers**, **Glossaries**, **Translation memory**.

### Billing page

`/app/settings/billing` shows:

- the two plans: **free with your key** and **$7 per managed book**;
- the **book total** for completed managed jobs;
- **Book orders** — one row per job with pages, blocks, amount and status.

A managed job is priced when it is created: **$7 flat up to 1,000 pages**, then
+$7 for each extra 1,000-page block. Failed and cancelled jobs are **No charge**.
Your-own-API jobs are **Free**. There is no prepaid wallet.

> **Note.** Payment collection is outside the app: `/app/settings/billing` is the
> order history your operator reconciles through their payment provider or
> invoice system.

---

## 13. Current limitations (verified)

- **No worker, no translation.** A separate worker process must be running.
- **EPUB and PDF only.** Despite the seeded `upload.allowed_extensions` list
  mentioning `txt` and `docx`, ingestion accepts only EPUB and PDF.
- **Email requires a PocketBase mailer.** Password reset and verification emails
  are sent by PocketBase, not by Book Fork.
- **Only OpenAI-compatible and Ollama provider adapters are implemented.** The
  Anthropic, Google Gemini and Custom endpoint catalog records have no adapter
  yet; testing or using them returns `unsupported_protocol`.
- **Glossary attachment** to a job/profile is not yet exposed in the UI.
- **Memory approval** is admin-only; the user review flow does not approve
  memory entries.
- **No self-service card checkout**; book orders are reconciled outside the app.
- **Single personal workspace per user.** Multi-user workspace invitations are
  modelled in data but not exposed as a user flow.

For problems, see [Troubleshooting](troubleshooting.md).
