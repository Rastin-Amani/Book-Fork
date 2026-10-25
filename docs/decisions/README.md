# Architecture Decision Records

Immutable records of the significant, hard-to-reverse decisions behind Book
Fork, in the order they were made. Each record states its **context**,
**decision** and **consequences**. Later records (and a few blockquote updates)
note where an earlier decision was extended; the original text is kept as the
historical record.

| ADR | Title | Decision |
| --- | --- | --- |
| [0001](0001-stack-and-versions.md) | Stack and version decisions | Python 3.14, Node 24 LTS, current stable backend/frontend releases; HTMX 2.x (not 4.x). |
| [0002](0002-language-libraries.md) | Language, locale, and detection libraries | `langcodes` + `language-data`, `Babel` (CLDR direction), `py3langid` offline detection. |
| [0003](0003-document-processing.md) | Document processing and PDF output | `zipfile`+`lxml` EPUB, PyMuPDF PDF, `pysbd` segmentation, pluggable render backend. |
| [0004](0004-translation-engine.md) | Universal translation engine design | Immutable `TranslationPlan`, single policy boundary, one generic provider adapter, structured output. |
| [0005](0005-durable-worker.md) | Durable worker, leases, and no Redis | Jobs-as-queue with leases; separate worker process; bounded async concurrency. |
| [0006](0006-providers-billing.md) | Providers, pricing, and credit accounting | Billing mode as data, generic pricing engines, capability/cost routing, idempotent credit ledger. |
| [0007](0007-product-ui.md) | Product UI architecture | Server-rendered HTMX shell, per-request repository bundle, polling, language-driven direction. |
| [0008](0008-flat-book-pricing.md) | Flat per-book pricing | BYOK free; managed $7/book per 1,000-page block; no credit wallet. |

## Adding a record

Copy the shape of an existing file: a title, the status/date header, then
Context, Decision and Consequences. Add a row to the table above and link it
from [`../README.md`](../README.md) if the audience list should surface it.
