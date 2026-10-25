# Universal translation engine

Source- and target-language agnostic. The engine consumes a resolved
`TranslationPlan` and canonical segments; it never inspects the language pair,
vendor, or model identity.

```
TranslationPlan + segments
        ↓
memory lookup (exact) ──hit──► reuse (no provider call, no charge)
        ↓ miss
glossary retrieval → context build → placeholder protection → batching
        ↓
provider (structured output, retries, error normalization)
        ↓
parse → segment-id/coverage validation → placeholder restoration
        ↓
normalization → validation → persist
```

## Translation plan (`app/translation/plan.py`)

Immutable dataclasses: `LanguageSpec` (tag/locale/script/direction),
`RetryPolicy`, `CreditPolicy`, `ContextPolicy`, `FallbackPolicy`, `UsageEstimate`
and `TranslationPlan`. A job executes the snapshot; it never re-reads mutable
settings. `plan.snapshot()` yields a JSON-serializable, reproducible record.

## Policy engine (`app/translation/policy_engine.py`)

`TranslationPolicyEngine.build_plan(PlanRequest)` validates both languages,
resolves the profile/connection/model (via model capabilities), selects the
active prompt version, and reads retry/context/pricing/fallback defaults from
**system settings** (never Python constants). Model routing is capability-driven:
a model may be strong for German→Japanese and weak for Japanese→Persian. There is
no `if source == "de" and target == "ja"`.

## Provider abstraction (`app/providers/`)

`TranslationProvider` normalizes `translate` / `estimate_usage` /
`validate_connection`. `OpenAICompatibleProvider` works against any
chat-completions endpoint; base URL, model, authentication, timeouts and limits
are configuration. Errors are categorized (`authentication_error`,
`invalid_request`, `rate_limited`, `timeout`, `provider_unavailable`,
`context_too_large`, `invalid_response`, `unknown_provider_error`); permanent
errors are never retried indefinitely.

**Own API keys:** `ProviderCredentialService` stores keys encrypted (Fernet) and
decrypts only to build a client. Keys are never logged and never returned to a
frontend. The `provider_credentials` collection has no public API rule.

## Structured output (`app/translation/structured.py`)

The response schema is generated from Pydantic models (`TranslationBatch` →
`TranslationItem`). Coverage is validated: every requested segment exactly once,
no unknown ids, no duplicates, no empty translations, strict extra-field
rejection. Ordering is never trusted. Unsupported structured output falls back to
a tolerant JSON parser; failures raise `invalid_response` and never become
successful translations.

## Prompting

Prompts live in the versioned `prompt_templates`/`prompt_versions` records and
are rendered by the sandboxed `PromptRenderer`. The engine composes composable
sections from context and configuration — base/source/target/style/domain/
formatting/glossary/quality — so no language-specific wording is hardcoded.

## Context (`app/translation/context.py`)

`TranslationContextBuilder` builds bounded document/chapter/previous/next context
under a configurable policy (`minimal`, `previous_segments`, `chapter_context`,
`adaptive`). Limits (`max_previous_segments`, `max_context_tokens`,
`max_glossary_terms`) come from settings. A whole book is never sent per call.

## Translation memory (`app/translation/memory.py`)

Exact matching only, always language-pair scoped (never by source hash alone).
Only **approved** entries are reused, and reuse incurs no provider call. New
translations are stored but not auto-approved.

## Glossary (`app/translation/glossary.py`)

Relevant terms are retrieved by exact/token matching (no vector search for V1) and
injected into the prompt. Preferred terminology is validated after translation;
forbidden terms are flagged. Retrieval is limited per request.

## Placeholder protection, normalization, validation

- `PlaceholderProtector` shields URLs/emails/markup/variables/code before the
  provider and restores after. Dropped or unrestorable placeholders **fail the
  attempt**.
- `TextNormalizationPipeline` is selected by target-language configuration
  (`unicode_nfkc`, `collapse_whitespace`, `strip_control`, `none`); it shields
  protected strings so they are never corrupted.
- `TranslationValidator` runs empty-result, placeholder, language-plausibility
  and glossary stages. A segment is only marked `completed` after the response is
  parsed, validated and restored.

## Batching, retries, fallback

- Batching uses `plan.batch_size`; batches never cross arbitrary section
  boundaries supplied by the caller.
- Retries use `RetryPolicy` and the normalized error category.
- Direct translation is the default. `FallbackPolicy.strategy` supports
  `fallback_model`, `fallback_provider` and `optional_pivot`;
  `translate_via_pivot` composes two passes and is a last resort, never the
  default.

## Usage accounting

Every request yields `input_tokens`, `output_tokens`, `provider_cost` and
`latency` where available. When exact usage is unavailable the provider marks the
value `estimated=True` — an estimate is never presented as exact.
