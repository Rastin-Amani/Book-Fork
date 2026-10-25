# Billing

Canonical reference. Two billing modes: **managed** (a flat-priced Book Fork
book) and **own_api** (the user's provider account). The pricing model is
[`pricing-strategy.md`](pricing-strategy.md): **free with your key; $7 per
managed book, up to 1,000 pages, +$7 per extra 1,000-page block**.

## Book orders

One managed translation job is one book order. The order snapshot is stored on
the job (`metadata.order`) when the job is created:

```
billing_mode   managed | own_api
pages          estimated pages (words / 300)
blocks         ceil(pages / 1,000)
amount         blocks × $7 (0 for own_api)
currency       USD
```

The billing page (`/app/settings/billing`) lists these orders. There is no
prepaid wallet and no token-based customer charge. Provider cost is still
recorded internally on the job (`estimated_provider_cost`,
`actual_provider_cost`) so the operator can monitor margin.

Failed and cancelled jobs are shown as **No charge**. Payment collection is
outside the app: `/app/settings/billing` is the customer-facing order history,
and operators reconcile it against their payment provider or invoice system.

## Pricing configuration

Pricing is configuration, not code (`seeds/system_settings.json`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `billing.book_price_usd` | `7.0` | Flat price for the first page block. |
| `billing.pages_per_block` | `1000` | Pages covered by one block; extra blocks add one price. |
| `billing.words_per_page` | `300` | Words-per-page factor used for the pre-translation estimate. |
| `billing.default_currency` | `USD` | Order currency. |

Formulas live in `app/billing/pricing.py`; estimation in
`app/billing/estimation.py`. Own-API jobs always quote `$0`.
