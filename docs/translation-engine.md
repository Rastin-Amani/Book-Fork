# Translation engine

Canonical reference. The engine is provider-agnostic and plan-driven: an immutable
`TranslationPlan` (resolved by the policy engine from persisted configuration) is
executed against a `TranslationProvider`, with context, glossary, translation
memory, normalization, validation, retries/fallback/pivot. Full detail in
[`translation.md`](translation.md); the decision record is
[ADR 0004](decisions/0004-translation-engine.md).

## The core requirement

> The Python codebase provides reusable translation/document-processing
> capabilities. Persisted configuration determines what Book Fork actually does.

Consequently no language pair, vendor, model, prompt, pricing rule, book price,
direction, normalization library or chunk length is hardcoded. Jobs persist their
plan snapshot so re-runs are deterministic and auditable. See
[`security-audit.md`](security-audit.md) for the hardcoding audit.
