# ADR 0004 — Universal translation engine design

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Phase 4 is the core AI system. It must be language-, provider- and model-agnostic,
driven entirely by configuration and persisted capabilities, with no hardcoded
language pairs, models, providers, prompts or language-specific normalizers. It
must also keep failure honest: a bad provider response must never become a
successful translation.

## Decision

- **Immutable plan.** `TranslationPlan` snapshots every decision (languages,
  profile, provider/model, prompt version, segmentation, context, normalization,
  validation, batch/temperature/token limits, retry/credit/fallback policy,
  usage estimate). Execution never re-reads mutable settings; `snapshot()` is
  reproducible.
- **Policy engine as the single routing boundary.** `TranslationPolicyEngine`
  validates the pair/capability and resolves the plan from records + settings.
  Routing logic does not live in the worker.
- **Provider abstraction with one generic adapter.**
  `OpenAICompatibleProvider` serves any chat-completions endpoint; a factory maps
  configured protocol types to adapters. No vendor is hardcoded.
- **Own-API-key mode.** Keys are encrypted at rest and decrypted only to build a
  client; never logged, never returned to the frontend.
- **Structured output generated from Pydantic models**, with strict coverage
  validation and a tolerant JSON fallback parser.
- **Deterministic validation.** Placeholder restoration and coverage are hard
  failures; language plausibility and glossary are soft unless configured strict.
- **Direct translation by default.** Pivot is an explicit, opt-in last resort
  (`translate_via_pivot`), never the default path.

## Consequences

- New providers are added by writing one adapter; new models/languages/prompts are
  data. No engine change is required to support a new language pair.
- Because the plan is a snapshot, replays and audits are deterministic.
- The worker becomes a thin consumer: load document segments, build a plan, call
  the engine, persist results.
- Provider-specific quirks are confined to adapters and the normalized error
  taxonomy; the engine only sees `ProviderResponse`/`ProviderError`.
