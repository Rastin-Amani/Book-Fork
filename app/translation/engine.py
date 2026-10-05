"""Universal translation engine.

Consumes a resolved :class:`TranslationPlan` and canonical segments and produces
validated translations. It is language-, provider- and model-agnostic: it never
inspects the language pair, vendor, or model identity.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.documents.placeholders import PlaceholderProtector
from app.exceptions import ConfigurationError, PromptRenderError
from app.prompts.renderer import PromptRenderer
from app.providers.base import (
    ProviderRequest,
    ProviderResponse,
    ProviderSegment,
    ProviderUsage,
    TranslationProvider,
)
from app.providers.errors import ProviderError
from app.translation.context import (
    ContextInputs,
    TranslationContextBuilder,
)
from app.translation.glossary import GlossaryMatch, GlossaryRetriever, glossary_lines
from app.translation.memory import TranslationMemoryStore
from app.translation.normalization import TextNormalizationPipeline, build_normalization_pipeline
from app.translation.plan import TranslationPlan
from app.translation.structured import (
    TranslationItem,
    map_translations,
    parse_translation_items,
    response_json_schema,
)
from app.translation.validation import TranslationValidator

SleepFn = Callable[[float], Awaitable[None]]
# Invoked after each batch is translated, so callers can persist progress
# incrementally instead of only once the whole document is done.
BatchCallback = Callable[
    [Sequence["TranslationSegmentInput"], "TranslationOutcome"], Awaitable[None]
]


@dataclass(frozen=True, slots=True)
class TranslationSegmentInput:
    id: str
    text: str
    section_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SegmentTranslation:
    segment_id: str
    translation: str | None
    status: str  # completed | failed
    source: str | None = None  # provider | translation_memory
    attempts: int = 0
    error_category: str | None = None
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TranslationOutcome:
    translations: Mapping[str, str]
    results: list[SegmentTranslation]
    usage: ProviderUsage
    memory_hits: int = 0
    failed: int = 0


class TranslationEngine:
    def __init__(
        self,
        *,
        protector: PlaceholderProtector | None = None,
        context_builder: TranslationContextBuilder | None = None,
        validator: TranslationValidator | None = None,
        prompt_renderer: PromptRenderer | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._protector = protector or PlaceholderProtector()
        self._context = context_builder or TranslationContextBuilder()
        self._validator = validator or TranslationValidator(self._protector)
        self._renderer = prompt_renderer or PromptRenderer()
        self._sleep = sleep or asyncio.sleep

    async def translate(
        self,
        plan: TranslationPlan,
        segments: Sequence[TranslationSegmentInput],
        *,
        provider: TranslationProvider,
        context_inputs: ContextInputs | None = None,
        memory: TranslationMemoryStore | None = None,
        glossary: GlossaryRetriever | None = None,
        persist_memory: bool = False,
        approved_memory: bool = False,
        fallback: tuple[TranslationProvider, str | None] | None = None,
        on_batch: BatchCallback | None = None,
    ) -> TranslationOutcome:
        if not segments:
            return TranslationOutcome(translations={}, results=[], usage=ProviderUsage())

        context_inputs = context_inputs or ContextInputs()
        results: dict[str, SegmentTranslation] = {}
        usage = ProviderUsage()
        memory_hits = 0
        pending: list[TranslationSegmentInput] = []

        for segment in segments:
            hit = None
            if memory is not None:
                hit = await memory.lookup(plan.source.tag, plan.target.tag, segment.text)
            if hit is not None:
                memory_hits += 1
                results[segment.id] = SegmentTranslation(
                    segment_id=segment.id,
                    translation=hit.translation,
                    status="completed",
                    source="translation_memory",
                )
            else:
                pending.append(segment)

        normalization = build_normalization_pipeline(plan.normalization_pipeline)

        for batch in _batches(pending, plan.batch_size):
            batch_result = await self._translate_batch(
                plan,
                batch,
                provider=provider,
                context_inputs=context_inputs,
                glossary=glossary,
                normalization=normalization,
                fallback=fallback,
            )
            usage = usage.merged(batch_result.usage)
            for item in batch_result.results:
                results[item.segment_id] = item
            if on_batch is not None:
                await on_batch(batch, batch_result)
            if persist_memory and memory is not None:
                await self._persist_batch(
                    batch, batch_result, plan, memory, approved=approved_memory
                )

        ordered = [results[segment.id] for segment in segments]
        translations = {
            item.segment_id: item.translation
            for item in ordered
            if item.status == "completed" and item.translation is not None
        }
        return TranslationOutcome(
            translations=translations,
            results=ordered,
            usage=usage,
            memory_hits=memory_hits,
            failed=sum(1 for item in ordered if item.status == "failed"),
        )

    async def _translate_batch(
        self,
        plan: TranslationPlan,
        batch: Sequence[TranslationSegmentInput],
        *,
        provider: TranslationProvider,
        context_inputs: ContextInputs,
        glossary: GlossaryRetriever | None,
        normalization: TextNormalizationPipeline,
        fallback: tuple[TranslationProvider, str | None] | None,
    ) -> TranslationOutcome:
        glossary_by_segment: dict[str, list[GlossaryMatch]] = {}
        lines: list[str] = []
        if glossary is not None:
            for segment in batch:
                matches = await glossary.relevant(
                    plan.source.tag,
                    plan.target.tag,
                    segment.text,
                    limit=plan.context_policy.max_glossary_terms,
                )
                glossary_by_segment[segment.id] = matches
                for line in glossary_lines(matches):
                    if line not in lines:
                        lines.append(line)

        built = self._context.build(
            plan.context_policy,
            replace(context_inputs, glossary_lines=tuple(lines)),
        )
        protected = {segment.id: self._protector.protect(segment.text) for segment in batch}
        provider_segments = [
            ProviderSegment(id=segment.id, text=protected[segment.id].text) for segment in batch
        ]
        prompt = self._render_prompt(plan, built, provider_segments)
        request = ProviderRequest(
            segments=provider_segments,
            user_prompt=prompt,
            model=plan.model_identifier,
            temperature=plan.temperature,
            max_output_tokens=plan.max_output_tokens,
            structured=True,
            response_schema=response_json_schema(),
        )

        requested_ids = [segment.id for segment in batch]
        try:
            response, attempts = await self._call_with_retry(provider, request, plan)
        except ProviderError as exc:
            if fallback is not None:
                fallback_provider, fallback_model = fallback
                try:
                    fallback_request = replace(request, model=fallback_model or request.model)
                    response, attempts = await self._call_with_retry(
                        fallback_provider, fallback_request, plan
                    )
                except ProviderError as fallback_exc:
                    return self._failed_outcome(batch, fallback_exc, attempts=0)
            else:
                return self._failed_outcome(batch, exc, attempts=0)

        try:
            mapping = self._extract(response, requested_ids)
        except ProviderError as exc:
            return self._failed_outcome(batch, exc, attempts=attempts)

        results: list[SegmentTranslation] = []
        for segment in batch:
            translated = mapping.get(segment.id)
            if not translated:
                results.append(
                    SegmentTranslation(
                        segment_id=segment.id,
                        translation=None,
                        status="failed",
                        attempts=attempts,
                        error_category="empty_translation",
                        error_message="The provider returned no translation for this segment.",
                    )
                )
                continue
            protected_segment = protected[segment.id]
            report = self._validator.validate(
                segment_id=segment.id,
                translated_text=translated,
                placeholder_mapping=protected_segment.mapping,
                target_script=plan.target.script,
                target_direction=plan.target.direction,
                glossary_matches=glossary_by_segment.get(segment.id, []),
                validation_profile=plan.validation_profile,
            )
            if not report.passed:
                results.append(
                    SegmentTranslation(
                        segment_id=segment.id,
                        translation=None,
                        status="failed",
                        attempts=attempts,
                        error_category="validation_failed",
                        error_message="; ".join(issue.message for issue in report.issues),
                        warnings=[issue.message for issue in report.warnings],
                    )
                )
                continue
            normalized = normalization.normalize(report.restored, protector=self._protector)
            results.append(
                SegmentTranslation(
                    segment_id=segment.id,
                    translation=normalized,
                    status="completed",
                    source="provider",
                    attempts=attempts,
                    warnings=[issue.message for issue in report.warnings],
                )
            )

        return TranslationOutcome(
            translations={
                r.segment_id: r.translation
                for r in results
                if r.status == "completed" and r.translation is not None
            },
            results=results,
            usage=response.usage,
        )

    def _render_prompt(
        self,
        plan: TranslationPlan,
        built: Any,
        provider_segments: Sequence[ProviderSegment],
    ) -> str:
        if not plan.prompt_body:
            raise ConfigurationError("No prompt template is configured for this plan.")
        profile = plan.profile_snapshot
        variables: dict[str, str] = {
            "source_language": plan.source.name or plan.source.tag,
            "source_locale": plan.source.locale or "",
            "target_language": plan.target.name or plan.target.tag,
            "target_locale": plan.target.locale or "",
            "style": str(profile.get("style") or ""),
            "tone": str(profile.get("tone") or ""),
            "domain": str(profile.get("domain") or ""),
            "source_segments": _format_segments(provider_segments),
            **built.as_prompt_variables(),
        }
        try:
            return self._renderer.render(plan.prompt_body, variables)
        except PromptRenderError as exc:
            raise ConfigurationError(str(exc)) from exc

    def _extract(self, response: ProviderResponse, requested_ids: list[str]) -> dict[str, str]:
        # Tolerant: a segment the model skipped or returned empty is left out
        # so it fails alone instead of failing the whole batch.
        if response.translations:
            items = [
                TranslationItem(segment_id=key, translation=value)
                for key, value in response.translations.items()
            ]
            return map_translations(items, requested_ids, tolerate_missing=True)
        items = parse_translation_items(response.content or "")
        return map_translations(items, requested_ids, tolerate_missing=True)

    async def _call_with_retry(
        self, provider: TranslationProvider, request: ProviderRequest, plan: TranslationPlan
    ) -> tuple[ProviderResponse, int]:
        policy = plan.retry_policy
        delay = policy.base_delay_seconds
        attempts = 0
        last_error: ProviderError | None = None
        for attempt in range(1, policy.max_attempts + 1):
            attempts = attempt
            try:
                return await provider.translate(request), attempts
            except ProviderError as exc:
                last_error = exc
                if (
                    not exc.retryable
                    or exc.category not in policy.retry_categories
                    or attempt >= policy.max_attempts
                ):
                    raise
                await self._sleep(min(delay, policy.max_delay_seconds))
                delay *= 2
        assert last_error is not None
        raise last_error

    @staticmethod
    def _failed_outcome(
        batch: Sequence[TranslationSegmentInput], exc: ProviderError, *, attempts: int
    ) -> TranslationOutcome:
        results = [
            SegmentTranslation(
                segment_id=segment.id,
                translation=None,
                status="failed",
                attempts=attempts,
                error_category=str(exc.category),
                error_message=exc.message,
            )
            for segment in batch
        ]
        return TranslationOutcome(translations={}, results=results, usage=ProviderUsage())

    async def _persist_batch(
        self,
        batch: Sequence[TranslationSegmentInput],
        outcome: TranslationOutcome,
        plan: TranslationPlan,
        memory: TranslationMemoryStore,
        *,
        approved: bool,
    ) -> None:
        source_by_id = {segment.id: segment.text for segment in batch}
        for result in outcome.results:
            if (
                result.status != "completed"
                or result.translation is None
                or result.source == "translation_memory"
            ):
                continue
            source_text = source_by_id.get(result.segment_id)
            if source_text is None:
                continue
            await memory.store(
                source_language=plan.source.tag,
                target_language=plan.target.tag,
                source_text=source_text,
                translation=result.translation,
                approved=approved,
            )


def _format_segments(segments: Sequence[ProviderSegment]) -> str:
    return "\n".join(f"[[{segment.id}]] {segment.text}" for segment in segments)


def _batches(
    segments: Sequence[TranslationSegmentInput], size: int
) -> list[list[TranslationSegmentInput]]:
    if size <= 0:
        size = 1
    return [list(segments[index : index + size]) for index in range(0, len(segments), size)]


async def translate_via_pivot(
    engine: TranslationEngine,
    segments: Sequence[TranslationSegmentInput],
    *,
    first_plan: TranslationPlan,
    first_provider: TranslationProvider,
    second_plan: TranslationPlan,
    second_provider: TranslationProvider,
    context_inputs: ContextInputs | None = None,
    glossary: GlossaryRetriever | None = None,
) -> TranslationOutcome:
    """Optional last-resort pivot translation (source -> pivot -> target).

    Direct translation is the default; callers only use this when a configured
    fallback strategy explicitly requests ``optional_pivot``.
    """
    first = await engine.translate(
        first_plan,
        segments,
        provider=first_provider,
        context_inputs=context_inputs,
        glossary=glossary,
    )
    pivot_segments = [
        TranslationSegmentInput(id=result.segment_id, text=result.translation)
        for result in first.results
        if result.status == "completed" and result.translation
    ]
    if not pivot_segments:
        return first
    second = await engine.translate(
        second_plan,
        pivot_segments,
        provider=second_provider,
        context_inputs=context_inputs,
        glossary=glossary,
    )
    return TranslationOutcome(
        translations=second.translations,
        results=second.results,
        usage=first.usage.merged(second.usage),
        memory_hits=first.memory_hits + second.memory_hits,
        failed=first.failed + second.failed,
    )
