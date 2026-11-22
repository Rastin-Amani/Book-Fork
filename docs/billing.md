# Billing and payments (Gumroad)

Canonical reference for how managed books are paid for. Two billing modes:
**managed** (a flat-priced Book Fork book, paid through Gumroad) and **own_api**
(the user's provider account, always free).

Pricing model: [`pricing-strategy.md`](pricing-strategy.md) — **free with your
key; $7 per managed book, up to 1,000 pages, +$7 per extra 1,000-page block**.

Billing is a generic service (`BillingService`) with one provider adapter
(`app/billing/payments/gumroad.py`). Invoice, allowance, entitlement and UI code
never read a Gumroad response directly; a future provider only implements
`app/billing/payments/base.py`.

## 1. The unit of sale

One managed translation job is one book order. When the job is created, the
price is computed **server-side** by `app/billing/pricing.py` and snapshotted on
the job (`metadata.order`):

```
billing_mode   managed | own_api
pages          estimated pages (words / 300)
blocks         ceil(pages / 1,000)
amount         blocks × $7 (0 for own_api)
currency       USD
```

The browser never supplies a price, amount, credit count, or entitlement. The
only client inputs are document/languages/profile/connection; the amount comes
from the plan estimate.

Provider cost is recorded separately (`estimated_provider_cost`,
`actual_provider_cost`) so operators can monitor margin. Customer money and
provider cost are never mixed.

Gumroad has **hosted checkout only**: there is no server-side checkout-session
API. Book Fork builds a Gumroad product URL for each invoice and redirects the
customer there. The product, its price floor and its custom field are created in
the Gumroad dashboard (§5).

## 2. Lifecycle

```
create managed job
      │
      ├── own_api ......................... queue immediately (free)
      │
      └── managed
            │
            ├── free allowance available → invoice paid (provider=free)
            │                             → job queued
            │
            └── otherwise → job status `awaiting_payment`
                          → invoice `pending` + correlation token
                          → customer opens hosted Gumroad checkout
                          → invoice `awaiting_payment`
                          → webhook (secret + API re-read) / status lookup
                                 ├── paid, product+amount+token match → `paid`
                                 │                                     → job queued once
                                 ├── amount short / product wrong     → `review`
                                 ├── refund / chargeback              → `refunded`
                                 ├── dispute                          → stays `paid` + note
                                 └── duplicate sale for paid invoice  → `paid` + review note
```

The translation worker only claims jobs whose status is `queued`, so no work
starts before an entitlement exists. A managed job is created as
`awaiting_payment`; `BillingService.fulfill` flips it to `queued` exactly once.

Invoice statuses: `pending`, `awaiting_payment`, `partially_paid`, `paid`,
`cancelled`, `failed`, `refunded`, `review`.

Rules:

- A sale is never trusted because a browser returned from checkout. Success is
  shown only after the sale is re-read from the Gumroad API and matched.
- Partial or short payment never grants a book.
- Overpayment pays the book; the actual amount is recorded and no extra
  entitlement is created.
- A late cancellation or refund never removes a delivered book; it records a
  compensating state.
- A failed/cancelled job is never charged (the invoice is a separate record and
  can be refunded in Gumroad).
- Every mutation is idempotent: `billing_events.event_key` has a unique index
  and processed deliveries are skipped.

### Correlation token

Each invoice gets a 32-byte URL-safe token (`correlation_token`, unique index)
generated with `secrets.token_urlsafe(32)`. It is placed in the Gumroad custom
field `Application Checkout Reference` on the hosted checkout URL and is the
**only** thing that associates a sale with an invoice. Internal user, workspace
and job ids are never sent to Gumroad.

The authoritative sale's `custom_fields` must contain the token. Email, amount
or a URL parameter alone never match a sale: `url_params` are attacker-editable
and are ignored for correlation. If the custom field is missing on the Gumroad
product (or the buyer's sale does not carry it), the invoice stays unpaid and an
operator reconciles it manually (§8).

## 3. Free allowance

A lifetime free managed-book allowance per workspace is configuration:

| Setting | Default | Meaning |
| --- | --- | --- |
| `billing.free_managed_books` | `1` | Free managed books per workspace (0 = none). |
| `billing.checkout_expiry_hours` | `24` | Hours before an unpaid checkout is replaced. |

Free books are claimed in `billing_free_claims` with a unique
`(workspace, kind, slot)` index. Two simultaneous first requests both try the
same slot; the database lets exactly one win, so the limit holds without a
multi-record transaction. Own-API jobs are always free and never consume a
claim. A claimed free book stays claimed even if the job later fails; an
operator can clear the claim row to restore goodwill.

## 4. Configuration

Billing is **opt-in** and off by default (managed books behave as before: no
charge, no checkout). A self-hosted install needs **no Gumroad credentials**;
missing credentials never turn billing on.

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `BILLING_ENABLED` | no | `false` | Enables checkout and enforcement. |
| `PAYMENT_PROVIDER` | when enabled | `gumroad` | Only `gumroad` is supported. |
| `GUMROAD_ACCESS_TOKEN` | when enabled | — | Seller API token; server-side only. |
| `GUMROAD_WEBHOOK_SECRET` | when enabled | — | Your own ≥32-character callback secret, **not** a Gumroad signing key. |
| `GUMROAD_PRODUCT_ID` | when enabled | — | Product id from the Gumroad API/dashboard (not the permalink). |
| `GUMROAD_PRODUCT_PERMALINK` | when enabled | — | Checkout slug, e.g. `book-fork` for `gumroad.com/l/book-fork`. |
| `GUMROAD_CUSTOM_FIELD_NAME` | no | `Application Checkout Reference` | Must match the product's custom field label exactly. |
| `GUMROAD_TIMEOUT_SECONDS` | no | `10` | Outbound API timeout. |
| `GUMROAD_ALLOW_TEST_SALES` | no | `false` | Fulfil `test=true` sales. Leave off in production. |

When `BILLING_ENABLED=true`, the app refuses to start without the Gumroad
values above. With billing enabled, trusted invoice writes also require
`POCKETBASE_SERVICE_CREDENTIAL`; the app returns a configuration error instead
of silently falling back to client-writable records.

> Never put the Gumroad token or webhook secret in a template, frontend bundle,
> or log. They are read only by the server-side adapter.

## 5. Gumroad setup

1. Create a **digital product** for managed books in the Gumroad dashboard,
   **listed in USD** (the server compares USD cents; amounts in another listing
   currency are not converted). It must be **pay-what-you-want** (the server
   passes the invoice amount as `price`). Set the minimum/suggested price to the
   lowest book price ($7) so a buyer cannot trivially underpay; short payments
   are still caught and sent to `review`.
2. Add a **custom field** to that product, labelled exactly
   `Application Checkout Reference` (or change `GUMROAD_CUSTOM_FIELD_NAME` to
   match). The field may be hidden/optional; it only needs to exist so the URL
   parameter is stored on the sale.
3. Copy the product **id** and **permalink**.
4. Create a Gumroad API application and generate an access token with
   `view_sales` (required to read sales and subscribe to them). The same token
   is used for authoritative lookups.
5. Generate a local secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Set it as `GUMROAD_WEBHOOK_SECRET`.
6. Set `BILLING_ENABLED=true`, `PAYMENT_PROVIDER=gumroad`, the four
   `GUMROAD_*` product/token values, `GUMROAD_WEBHOOK_SECRET`, and
   `POCKETBASE_SERVICE_CREDENTIAL`.
7. Register resource subscriptions for the token (one call per resource):
   `sale`, `refund`, `dispute`, `dispute_won`, `cancellation`,
   `subscription_updated`, `subscription_ended`, `subscription_restarted`:

   ```bash
   curl -X PUT https://api.gumroad.com/v2/resource_subscriptions \
     -H "Authorization: Bearer $GUMROAD_ACCESS_TOKEN" \
     -d "resource_name=sale" \
     -d "post_url=https://<your-host>/api/webhooks/gumroad?secret=<GUMROAD_WEBHOOK_SECRET>"
   ```

   Repeat with each `resource_name`. Gumroad does **not** sign API resource
   notifications; the `?secret=` value is the local credential. Because it
   travels in a URL, it can appear in proxy/access logs: keep those private and
   rotate the secret (and re-register the subscriptions) if it leaks. Optionally
   also set a Ping URL (account settings) — pings are signed only if signing is
   enabled there, and Book Fork verifies `X-Gumroad-Signature` when present.
8. Run migrations (`pocketbase migrate`) and seed (`make seed`).
9. Make a real test purchase in staging with the smallest amount. Confirm the
   invoice reaches `paid`, the job reaches `queued`, and the success message
   appears only after the API verification. Then refund it and confirm the
   invoice reaches `refunded` while the delivered book stays available.

If the custom field does not appear on the sale, stop and fix the product
configuration; do not "fix" matching by email or amount.

## 6. Provider contract

`app/billing/payments/gumroad.py` uses only documented endpoints:

- Checkout: `https://gumroad.com/l/<permalink>?wanted=true&email=...&price=...&Application%20Checkout%20Reference=<token>`.
  `wanted=true` opens checkout directly; `price` is in major units for a
  pay-what-you-want product. The URL is rejected unless it is `https` on
  `gumroad.com` (or a subdomain) under `/l/`.
- Sale: `GET /v2/sales/:id`; amount fields are integers in **USD cents**
  whatever the listing currency is. `GET /v2/sales?email=&product_id=` is used
  to recover a missed notification, then each candidate is re-read by id.
- Subscription: `GET /v2/subscribers/:id`.
- Notifications: `application/x-www-form-urlencoded`, with bracket keys such as
  `custom_fields[Application Checkout Reference]`. API resource subscriptions
  carry no Gumroad signature.

## 7. Webhook processing

`POST /api/webhooks/gumroad` is the only unauthenticated billing route. It:

1. Requires `application/x-www-form-urlencoded` (415 otherwise).
2. Rejects payloads over 256 KB (413), streaming with a hard bound because
   `Content-Length` is advisory.
3. Requires `?secret=` equal to `GUMROAD_WEBHOOK_SECRET` in constant time
   (401 otherwise). If a signed Ping carries `X-Gumroad-Signature`, the
   `t`/`v1` HMAC of the raw body is verified too, with a 5-minute window.
4. Parses the form body only after authentication.
5. Deduplicates by a stable event key (`sale:<id>`, `refund:<id>`,
   `cancellation:<subscription>:<time>`, ...) through the unique
   `billing_events.event_key` index.
6. Resolves the invoice by correlation token, then provider sale id, then
   subscription id. An unknown sale is recorded and acknowledged, never
   fulfilled.
7. Re-reads the sale or subscription from the Gumroad API. Only then applies
   product, amount, refund, dispute or subscription state.

Return codes: `2xx` for accepted/duplicate/unknown-invoice deliveries (so
Gumroad stops retrying), `400` malformed payload, `401` bad secret/signature,
`413` too large, `415` wrong content type, `500` temporary storage/provider
failure (Gumroad retries), `503` billing not configured.

**The return URL is never trusted.** It may show a "pending" screen; success is
shown only after the sale is verified.

## 8. Reconciliation, refunds, disputes, subscriptions

- Opening an invoice performs a lookup when it is open and has a provider
  reference or correlation token. The invoice page polls a status partial every
  5 seconds. **Check status** calls `POST .../reconcile` behind session + CSRF.
- Operators list open invoices at `/admin/billing` and can reconcile there.
- **Refund / chargeback:** the original amount, `paid_at` and `fulfilled_at`
  stay intact; `refunded_at` and a snapshot are added, status becomes
  `refunded`. A delivered book is not revoked by default. Refund in the Gumroad
  dashboard; the notification updates Book Fork.
- **Partial refund:** status stays `paid`, `failure_reason` asks for review.
- **Dispute:** a dispute is not a final chargeback. A paid book keeps access
  with a note; an unpaid invoice goes to `review`. `dispute_won` clears the
  dispute note.
- **Subscriptions:** Book Fork sells one book per invoice, not a recurring plan.
  Membership notifications are still handled defensively: cancellation records
  `cancelled_at` without revoking the paid book before the period ends;
  `subscription_ended` cancels only an invoice that never paid; restart and
  upgrade/downgrade events are recorded in invoice metadata. Renewal charges are
  recorded once per sale id and never grant a second book.
- **Manual reconciliation:** if a sale has no token (misconfigured product
  custom field), find it in Gumroad by email and date, confirm the amount, then
  in PocketBase set `provider_reference` to the sale id, status `paid`, and set
  the job to `queued` deliberately. Do not delete the invoice or events.

## 9. Operations and troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| App fails at start: `billing_enabled=true requires: gumroad_access_token, ...` | Enabled without config | Set the Gumroad values, or disable billing. |
| App fails: `Billing requires POCKETBASE_SERVICE_CREDENTIAL` | Enabled without trusted writes | Set the service credential. |
| Job says "Payment required" forever | Webhook not registered / custom field missing | Check resource subscriptions and the product custom field; use **Check status**. |
| Webhook returns 401 | Wrong/missing `?secret=` or bad signature | Compare with `GUMROAD_WEBHOOK_SECRET`; rotate both sides together. |
| Webhook returns 415 | Proxy rewrote the content type | Preserve `application/x-www-form-urlencoded`. |
| Invoice stuck `review` | Amount short, wrong product, missing token, test sale | Inspect the sale in Gumroad; refund or reconcile manually. |
| Invoice `pending`, no checkout URL | Customer has not clicked Pay | Expected; the checkout is created on demand. |
| Redirect rejected: `untrusted checkout URL` | Bad permalink | Fix `GUMROAD_PRODUCT_PERMALINK`; inspect logs (no secrets logged). |
| Duplicate webhook | Gumroad retries | Safe: event key + unique index make it a no-op. |
| Job never starts after payment | API lookup or fulfillment failed | Check `billing_events.error`; re-open the invoice or press Check status. |

Structured events: `billing_invoice_created`, `billing_checkout_created`,
`billing_payment_received`, `billing_signature_failed`, `billing_fulfilled`,
`billing_fulfillment_failed`, `billing_reconciled`, `billing_refunded`,
`billing_disputed`. Logs never contain tokens, secrets or buyer card data.

## 10. Data model

| Collection | Purpose | Client access |
| --- | --- | --- |
| `billing_invoices` | One row per book order; amount, status, provider sale/subscription references, correlation token, snapshots. | Read own workspace; all writes server-only. |
| `billing_events` | Notification deliveries and processing outcome. | No client access. |
| `billing_free_claims` | Bounded free-book slots. | Read own workspace; writes server-only. |

`awaiting_payment` is added to `translation_jobs.status`. Migration
`1750000200_gumroad_billing.js` adds `correlation_token`,
`provider_subscription_id` and `refunded_at`, the `gumroad` provider value, the
notification event types, and unique/index constraints. It is additive:
historical PayRam invoices/events remain readable (`payram` stays a valid
provider value) and are never deleted.

Money is stored in the invoice currency (USD). Historic rows are never mutated
to hide an event; compensating state (`refunded`, `review`) is recorded instead.

## 11. Tests

- `tests/unit/test_billing_pricing.py`, `test_billing_estimation.py` — price math.
- `tests/unit/test_billing_service.py` — allowance, checkout, sale matching,
  short/over payment, duplicate sale, refunds, chargebacks, partial refunds,
  disputes, renewals, cancellation, termination, restart, idempotency.
- `tests/unit/test_gumroad_provider.py` — checkout URL construction, form
  parsing, event inference, callback secret, optional Ping signature, sale and
  subscription normalization, pagination and API failures (mocked transport).
- `tests/integration/test_billing_web.py` — managed job gating, free allowance,
  webhook secret/content-type/size handling.
- `tests/unit/test_config.py` — self-hosted defaults and enabled-billing
  validation.

**Verification status:** all Gumroad interaction is mocked; no Gumroad
credentials, product or webhook endpoint were available in this environment. A
real purchase, a real refund and a real membership lifecycle have **not** been
exercised here. The staging checklist in §5 is the remaining manual
verification, and a successful automated test is not evidence of a real payment.
