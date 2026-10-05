# Providers, model routing & credit accounting

Phase 6 makes Book Fork commercially usable: pluggable providers, encrypted user
credentials, SSRF protection, capability/cost-aware routing, and auditable
credit accounting distinct from provider cost.

## Provider modes

A `provider_connections` record has a `billing_mode`:

- **`managed`** — a Book Fork-owned connection; usage consumes Book Fork credits.
- **`own_api`** — the user's endpoint/key; **zero Book Fork credits** (the provider
  cost is the user's), though usage metadata is still recorded.

Book Fork-managed vs user-owned is therefore data, not a hardcoded branch. When a
user selects their own connection, the policy engine uses it (unless invalid/
unavailable) and never silently spends Book Fork credits elsewhere.

## Adapters

`TranslationProvider` (the `LLMProvider` abstraction) is protocol-agnostic;
`OpenAICompatibleProvider` serves any chat-completions endpoint and the factory
maps configured protocol types to adapters. Adding Anthropic/Gemini/Azure/Ollama
later means one adapter each — the engine is untouched. Ollama already works via
the OpenAI-compatible adapter.

## Credential security

User API keys are encrypted at rest (Fernet, keyed by `ENCRYPTION_KEY`), stored
in `provider_credentials` (no public API rule), decrypted only to build a client,
never logged, and never returned through any response. The key is never derived
from a user password.

## Connection testing

`ProviderConnectionTester` returns a secret-free diagnostic:
`connected`, `authentication_failed`, `model_unavailable`,
`endpoint_unreachable`, `unsupported_protocol`, `unsafe_url`.

## SSRF protection

Custom provider URLs are untrusted. `app/security/urls.py` blocks loopback,
private (RFC1918), link-local, reserved and metadata addresses, rejects
credentials-in-URL and non-HTTP(S) schemes, and resolves DNS before connecting.
`ProviderRuntime` validates every endpoint (private endpoints require explicit
`allow_private`, e.g. a self-hosted Ollama). The OpenAI-compatible adapter also
disables redirects, applies connect/request timeouts, and enforces a response
size ceiling.

## Model registry & capability matrix

`provider_models` records identifier, context window, output limits, structured/
vision capability, `quality_score`, `enabled`, and generic pricing:
`input_cost_per_million_tokens`, `output_cost_per_million_tokens`, and an
optional flat `request_cost`. `model_capabilities` records per (model, source
language, target language) support, preference, quality and notes. Routing is
data-driven.

## Quality modes

`best`, `balanced`, `quality`, `fast` and `economy` are configurable tiers, not
provider names. The policy engine ranks candidate models by mode:

- `best`/`quality` → maximise capability/quality;
- `balanced` → quality first, cost as a tie-breaker;
- `fast`/`economy` → minimise configured cost, quality as a tie-breaker.

No model name is embedded in a tier's meaning.

## Credit accounting

Provider cost and Book Fork credits are kept separate. The worker tracks estimated
and actual values for both:

```
estimated provider cost   actual provider cost
estimated credits         reserved credits   actual credits   refund
```

Flow: **estimate → reserve → translate → settle (release hold, charge actual) →
refund unused**. Reservations are reference-guarded (`job:<id>:reserve`), so a
worker crash cannot double-charge.

### Ledger

`credit_transactions` types: `purchase`, `bonus`, `reservation`, `consumption`,
`refund`, `adjustment`, `expiration`; each carries amount, type, workspace,
`job`, `reference`, `balance_before`, `balance_after`. History is append-only.

### Own-API mode

`CreditPricingEngine` returns **0 credits** when `billing_mode == own_api`, while
provider cost is still computed and recorded. This is configuration, not a
special branch in the worker.

## Cost & estimation engines

- `ProviderPricingEngine` — model pricing × usage → provider cost.
- `CreditPricingEngine` — tokens and/or provider cost → Book Fork credits (per
  1000 tokens and/or a markup on provider cost), honouring billing mode.
- `estimate_from_texts` — source words, characters, estimated input/output
  tokens, estimated provider cost and estimated credits. Everything is marked
  `estimated`.

Formulas live in `app/billing/`, never scattered through the worker.

## UI-facing estimates

`app/billing/estimation.py` provides the reusable estimate shown before
confirmation ("~ N source words, ~ M credits"). It is wired into the
new-translation workflow: `POST /app/translations/estimate` renders
`partials/estimate.html` with source words, estimated input tokens, the resolved
provider/model and either the estimated credits or a "your own API" notice. The
estimate is always labelled approximate. See [`ui.md`](ui.md) and the
[User Guide](user-guide.md).
