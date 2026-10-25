# Book Fork — Pricing Strategy (v3: cheap flat per book)

> Supersedes v2. Numbers are recommendations to validate, not shipped facts.
> Costs derive from `app/billing/estimation.py` and July-2026 provider pricing.

## 1. The model

- **BYOK — free.** Your own OpenAI-compatible key. Unlimited books. You pay
  your provider directly.
- **Managed — $7 per book, flat, up to 1,000 pages.** Same price at 100 pages or
  1,000.

One number, no credits, no tiers, no seats.

## 2. Why cheap is possible: the lever is the model, not the margin

The old $29 was priced against a *balanced* model (~$8 to translate a
1,000-page book). On an **economy/fast model** the same book costs **~$0.50**.
That is the whole reason the price can drop 4× and still keep healthy margin.

Planning math: ~300 words/page, ~6 chars/word, 4 chars/token, output ≈ input,
+35% context overhead → **~1,200 tokens/page**. Economy model ≈ **$0.35 per
million blended tokens** (55% input / 45% output), +15% retry buffer.

| Book | Tokens | Managed cost (economy) | At **$7** gross margin |
| --- | --- | --- | --- |
| 100 pages (30k words) | ~120k | ~$0.05 | **99%** |
| 300 pages (90k words) | ~360k | ~$0.15 | **98%** |
| **1,000 pages (300k words)** | ~1.2M | **~$0.49** | **93%** |

After the payment fee (~2.9% + $0.30 ≈ $0.50), the biggest book still nets
~86%. Nothing is underwater; the small books just carry more margin than the
big one, which is exactly what a flat price needs.

## 3. The honest trade-off: cheap price = economy model

You cannot have both a $7 managed price *and* a frontier model on a 1,000-page
book — a premium model costs ~$13-17 there, which would lose money.

So the managed plan uses **one fixed economy/fast model** (a modern
Flash/mini-class model — genuinely decent for translation, not a toy). If a
customer wants a stronger model, that is what **BYOK is for**: free, any model,
their own account. This is the clean split:

| | Managed $7 | BYOK free |
| --- | --- | --- |
| Model | one fixed economy/fast model | any model you choose |
| Price | $7/book | $0 (you pay provider) |
| Who it is for | authors, one-off books, price-sensitive | power users, agencies, quality-critical work |

That split lets you be cheap without either losing money or lying about quality.

## 4. Floor and ceiling

- **$5/book** — aggressive but safe on an economy model: ~81% net on a
  1,000-page book after fees. Use it if adoption matters more than buffer.
- **$7/book — recommended.** ~86% net worst case, room for refunds, support and
  a model upgrade later, and still an impulse price for an author.
- **$9/book** — more buffer; only worth it if you expect a lot of large books.
- **Below ~$4** — the payment fee, refunds and support start to dominate; not
  worth it at a 1,000-page cap.

A stronger *managed* model is a different product: it needs ~$19-29/book to
stay healthy. Keep that as an optional future tier, or send those users to BYOK.

## 5. The page cap is still non-negotiable

One flat price only survives if the worst case is bounded. Keep **1,000 pages
(~300k words)** per book. Above that, charge **+$7 per additional 1,000-page
block**. Enforce it at estimate/upload, before the job runs.

Without the cap, a 5,000-page PDF at $7 is an open loss. With it, "100 and
1,000 pages cost the same" stays true and safe.

## 6. Does it hurt anybody?

- **Big-book buyer:** $7 vs ~$36-45 for classic MT (without structure), ~$57-117
  for AI book services, ~$24k+ for a human. Absurdly good.
- **Small-book buyer:** $7 vs ~$4 for raw Google MT. Close enough that the
  finished-book story (structure, glossary, resume, export) clearly wins.
- **Operator:** 86-99% net margin, bounded downside thanks to the cap.
- **Quality:** the one real risk. A cheap model is not a frontier model. Be
  honest on the page, and keep BYOK as the free upgrade path.

## 7. Product changes

- Remove credits from the UI. Show "Free with your key · $7 per book."
- Keep the cost/estimate engine internally to watch margin; replace the customer
  credit wallet with a simple **book order** (one paid job = one order).
- Enforce the page cap at estimate; keep `limits.*`/`retention.*` as BYOK
  fair-use caps, not a paywall.

## 8. One-line recommendation

**BYOK free; managed $7 per book flat, up to 1,000 pages, on one fixed
economy/fast model; +$7 per extra 1,000-page block.** Cheap enough to be an
impulse buy, ~86% net even on the largest book, and 5× under classic MT for the
same document.
