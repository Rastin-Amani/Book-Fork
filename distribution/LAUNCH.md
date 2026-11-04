# Book Fork — launch copy

Finished copy for the first public launch. Adapt the opening line to the room;
keep the facts unchanged. Disclosure: you are the maintainer.

- Repository: <https://github.com/Rastin-Amani/Book-Fork>
- Website: <https://bookfork.space>
- Managed app: <https://app.bookfork.space>
- Version: v0.6.1 (pre-1.0, MIT)
- Contact: GitHub issues; security reports through `SECURITY.md`

## One-liner

Self-hosted EPUB and PDF book translation with your own LLM or managed credits —
glossaries, review, and resumable jobs without Redis or Celery.

## Short description (directories, 160 chars)

Translate EPUB and PDF books between 60 languages with any OpenAI-compatible
LLM. Self-hosted, MIT, resumable jobs, review, glossaries. $7/book managed.

## Hacker News — Show HN (human-only)

HN asks that submission text be written and edited by a person. Use the facts
below to write your own post; do not paste this section verbatim.

**Title options**

- Show HN: Book Fork – self-hosted EPUB/PDF translation with resumable jobs
- Show HN: I built a book translator that survives a failed LLM call
- Show HN: Translate whole books with your own LLM (MIT, FastAPI)

**Facts to include**

- It parses EPUB and PDF into a canonical book model, segments by structure,
  protects placeholders, and exports EPUB and PDF.
- The worker claims jobs from PocketBase with leases, retries with backoff,
  resumes failed segments without redoing validated ones, and does not need
  Redis or Celery.
- Provider support is one OpenAI-compatible adapter plus Ollama. Anthropic and
  Gemini catalog records exist but need adapters.
- There is a review screen; edited segments can be approved into translation
  memory and reused with no provider call.
- Self-hosting is MIT. The managed option is a flat $7 per book up to 1,000
  pages, plus $7 per extra block.
- 60 seeded languages; language metadata comes from CLDR.
- Known gaps: OAuth-only sign-in, no glossary attachment in the UI yet, no
  general REST API, and no self-service card checkout.

## Reddit — r/selfhosted

**Title:** I built a self-hosted book translator that resumes after a failed LLM call

**Body:**

I translate long books, and every tool I tried had the same failure mode: one
bad provider response in chapter nine, and I start over.

Book Fork treats a translation as a job instead of a long prompt. It parses an
EPUB or PDF, segments it by structure, and a separate worker translates,
validates, and writes segments as they complete. Leases and retries are stored
in PocketBase, so a crashed or rate-limited worker resumes without redoing
validated paragraphs. No Redis or Celery.

A few details that matter in practice:

- Placeholders and inline markup are protected before the LLM sees the text.
- You can review every paragraph side by side, edit it, and approve it.
- Approved segments become translation memory and are reused per exact language
  pair with no provider call.
- Providers are OpenAI-compatible endpoints (OpenAI, vLLM, LiteLLM, gateways)
  or local Ollama. Keys are encrypted at rest.
- Output is EPUB and PDF.

It is MIT and runs with Docker Compose. There is also a managed option at $7 per
book if you do not want to run the worker, but the self-hosted version is the
point.

Repo and screenshots: https://github.com/Rastin-Amani/Book-Fork

Known gaps I would rather state up front: sign-in is Google/GitHub OAuth only,
glossaries can be managed but are not yet attachable from the job screen, and
there is no general REST API. I am interested in feedback from people who
actually translate full-length books, especially around PDF layout fidelity and
provider failure modes.

## Reddit — r/opensource

**Title:** Book Fork: MIT-licensed EPUB/PDF translation with a durable worker and provider-agnostic core

**Body:**

Book Fork is a server-rendered FastAPI + HTMX app for translating whole books
between 60 languages. The part I think is worth a look is the architecture:
translation behaviour is configuration in PocketBase (languages, models,
prompts, profiles, pricing, limits), while the engine is a small provider-agnostic
core with one OpenAI-compatible adapter.

The worker is a separate asyncio process. It claims jobs with leases, retries
with backoff, resumes failed segments, and finalizes EPUB/PDF output. No Redis,
no Celery, no extra queue.

It is pre-1.0 and honest about its gaps: OAuth-only login, two provider
protocols, no glossary attachment in the UI yet, personal workspaces only.

MIT, 427 tests, CI runs ruff + strict mypy + pytest.

https://github.com/Rastin-Amani/Book-Fork

## Product Hunt

**Tagline:** Translate whole books, not chat snippets.

**Description:**

Book Fork turns an EPUB or PDF into a translated book — with the structure,
placeholders, and terminology intact.

Upload a book, choose the language pair and quality profile, and a durable worker
translates it in resumable segments. Review and edit any paragraph side by side,
approve it into translation memory, then download EPUB and PDF.

Use your own OpenAI-compatible provider and pay them directly, or use managed
credits at a flat $7 per book. Self-host it under MIT, or use the hosted app.

60 languages. Glossaries. Resumable jobs. No Redis or Celery.

**First comment:**

Hi Product Hunt — I built Book Fork because translating a full book is an
operations problem, not a prompt problem.

A book has chapters, footnotes, placeholders, and names that need to stay
consistent across hundreds of pages. A single failed model call should not throw
away the work already done. So the product is built around a durable worker:
jobs are leased, retries are bounded, validated segments are kept, and the final
EPUB/PDF is assembled only when the book is complete.

The open-source version is the full product. Connect an OpenAI-compatible
endpoint or local Ollama and use your own key; the managed option exists for
people who do not want to run a worker.

What I would love feedback on: PDF layout fidelity, glossary workflows, and the
review experience for long books. Known gaps are listed in the README — OAuth
only, no glossary attachment in the UI yet, and no self-service checkout.

## X / Twitter thread

**1/**

Translating a book is not a chat prompt. It is thousands of segments, a worker
that can fail, and names that must stay consistent.

I built Book Fork: self-hosted EPUB/PDF translation with resumable jobs, review,
and memory. MIT.

https://github.com/Rastin-Amani/Book-Fork

**2/**

The worker claims jobs with leases, retries with backoff, and resumes failed
segments without redoing validated ones. No Redis. No Celery.

Output is EPUB and PDF.

**3/**

Bring your own OpenAI-compatible LLM or local Ollama. Keys are encrypted at
rest.

Managed option: $7 per book up to 1,000 pages.

60 languages. Pre-1.0, and the gaps are documented.

## LinkedIn

I kept losing book translations halfway through.

A single rate limit in chapter nine meant starting over, and a wall of chat text
is not a deliverable I can send to a reader. So I built Book Fork around a
durable worker instead: EPUB/PDF in, structured segments out, review, then EPUB
and PDF back.

It is self-hosted and MIT licensed. You can connect any OpenAI-compatible
provider or local Ollama and pay them directly, or use the managed option at $7
per book. There are 60 languages, glossaries, and translation memory.

It is pre-1.0 and the README lists the limitations rather than hiding them:
OAuth-only sign-in, two provider protocols, no glossary attachment in the UI yet.

If you translate books, publish them, or run a studio, I would value feedback on
the review workflow and PDF fidelity.

https://github.com/Rastin-Amani/Book-Fork

## Directory submission blurb (short)

Book Fork is an MIT-licensed, self-hosted translator for EPUB and PDF books.
It uses any OpenAI-compatible LLM or local Ollama, keeps jobs resumable with a
leased worker, supports 60 languages, glossaries, translation memory, and
side-by-side review, and exports EPUB and PDF. No Redis or Celery.
