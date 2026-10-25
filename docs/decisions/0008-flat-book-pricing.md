# ADR 0008 — Flat per-book pricing

- **Status:** Accepted
- **Date:** 2026-10-24
- **Supersedes:** the credit-pricing parts of [ADR 0006](0006-providers-billing.md)

## Context

Token-based credits made customers reason about an internal unit and made the
final charge unpredictable. On an economy/fast model a 1,000-page book costs
roughly $0.50 in provider usage, so a flat price can keep a healthy margin while
being an impulse purchase.

## Decision

- **BYOK is free.** Own-API connections never create a Book Fork charge.
- **Managed is $7 per book**, flat for up to 1,000 pages. Each additional
  1,000-page block adds $7.
- Price is derived from **estimated pages**, not tokens. The page factor and
  block size are `billing.*` settings.
- One managed job is one **book order**, stored in `translation_jobs.metadata.order`
  (pages, blocks, amount, currency). There is no customer credit wallet.
- Provider cost is still recorded on the job for internal margin monitoring.
- Failed and cancelled jobs are not charged.

## Consequences

- The pricing engine (`app/billing/pricing.py`) is a pure page-to-price
  calculation; the ledger and wallet are gone.
- The customer UI shows pages and a flat price, never credits.
- The page block bounds the worst case. Larger books pay proportionally more
  instead of becoming an open loss.
- Payment collection is external: the billing page is an order history that an
  operator reconciles with their payment provider or invoice system.
- Legacy `credit_*` and `usage_events` collections remain in old databases but
  are no longer read or written.
