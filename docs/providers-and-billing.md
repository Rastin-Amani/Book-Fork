# Providers, model routing & book billing

Phase 6 makes Book Fork commercially usable: pluggable providers, encrypted user
credentials, SSRF protection, capability/cost-aware routing, and flat per-book
pricing distinct from provider cost.

## Provider modes

A `provider_connections` record has a `billing_mode`:

- **`managed`** — a Book Fork-owned connection; the job becomes a $7 book order.
- **`own_api`** — the user's endpoint/key; **free** (the provider cost is the
  user's), though provider cost is still recorded for diagnostics.

Book Fork-managed vs user-owned is therefore data, not a hardcoded branch. When a
user selects their own connection, the policy engine uses it (unless invalid/
unavailable) and never silently falls back to a managed connection.

## Adapters

`TranslationProvider` (the `LLMProvider` abstraction) is protocol-agnostic;
`OpenAICompatibleProvider` serves any chat-completions endpoint and the factory
maps configured protocol types to adapters. **Implemented today:
`openai_compatible` and `ollama`** (the latter via the OpenAI-compatible
adapter). The `anthropic`, `gemini` and `custom` records in the seed catalog are
protocol stubs with no adapter yet — building one raises a `ConfigurationError`,
surfaced by the connection test as `unsupported_protocol`. Adding Anthropic,
Gemini, Azure or another protocol later means one adapter each — the engine is
untouched.

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

## Book orders and provider cost

Provider cost and customer price are kept separate. Each managed job stores an
order snapshot (`metadata.order`: pages, blocks, amount, currency) and the worker
records actual provider cost on the job for margin monitoring. There is no
prepaid wallet.

Flow: **estimate pages → quote book price → translate → record actual provider
cost**. The customer price never changes with token usage.

### Own-API mode

`BookPricingEngine` returns **$0** when `billing_mode == own_api`, while provider
cost is still computed and recorded. This is configuration, not a special branch
in the worker.

## Cost & estimation engines

- `ProviderPricingEngine` — model pricing × usage → provider cost (internal).
- `BookPricingEngine` — estimated pages → book blocks and flat price.
- `estimate_from_texts` — source words, characters, estimated input/output
  tokens, estimated pages, provider cost and book price. Everything is marked
  `estimated`.

Formulas live in `app/billing/`, never scattered through the worker.

## UI-facing estimates

`app/billing/estimation.py` provides the reusable estimate shown before
confirmation ("~ N source words, ~ M pages, $7"). It is wired into the
new-translation workflow: `POST /app/translations/estimate` renders
`partials/estimate.html` with source words, estimated pages, the resolved
provider/model and either the book price or a "free with your key" notice. The
estimate is always labelled approximate. See [`ui.md`](ui.md) and the
[User Guide](user-guide.md).
