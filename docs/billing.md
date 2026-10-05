# Billing & credits

Canonical reference. Two billing modes: **managed** (Book Fork credits) and
**own_api** (the user's provider account). Provider cost and Book Fork credits are
kept separate; formula engines are centralized in `app/billing/`. The full model
is in [`providers-and-billing.md`](providers-and-billing.md).

## Ledger integrity

`credit_wallets` holds a running balance; `credit_transactions` is the audit trail
and source of truth. Every mutation writes a transaction with balance-before/after
and an idempotency `reference` (`job:<id>:reserve`, `job:<id>`,
`job:<id>:cancel-refund`, `admin:<wallet>:…`). Balances are **never** mutated
silently — including manual admin grant/remove/refund, which go through the ledger
(`/admin/credit-wallets/{id}/ledger`).

Credit pricing (`credits_per_1000_tokens`, `provider_cost_markup`,
`credit_reservation_multiplier`, `default_currency`) is configuration, not code.
