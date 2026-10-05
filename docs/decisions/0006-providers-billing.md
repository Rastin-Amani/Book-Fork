# ADR 0006 — Providers, pricing, and credit accounting

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Phase 6 makes Book Fork commercially usable. It must support Book Fork-managed and
user-owned providers, encrypt user keys, defend against SSRF from custom URLs,
route by model capability *and* cost, and keep auditable credit accounting
separate from raw provider cost.

## Decision

- **Billing mode is data.** `provider_connections.billing_mode` is `managed` or
  `own_api`; own-API connections consume zero Book Fork credits while still
  recording usage. No hardcoded "own key" branch.
- **Generic pricing.** Model pricing (input/output per million tokens + optional
  flat request cost) is database configuration. `ProviderPricingEngine` and
  `CreditPricingEngine` centralize the formulas; `estimate_from_texts` produces
  clearly-marked estimates.
- **Mode-aware routing.** Quality tiers (`best`/`balanced`/`quality`/`fast`/
  `economy`) rank capability and cost; model names are never embedded in a tier.
- **SSRF is enforced at build and test time**, with private endpoints requiring
  explicit opt-in.
- **Reservation is idempotent** and reference-guarded; settlement releases the
  hold and charges actual usage.

## Consequences

- New providers are adapters; new models/languages/pricing/quality tiers are
  data.
- Credit accounting is auditable and crash-safe; provider cost and credits never
  conflate.
- The estimate service is ready for the frontend to surface pre-confirmation;
  wiring the endpoint/UI is deferred to the frontend phase.
