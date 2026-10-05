"""Universal translation engine: batching, retries, memory, validation."""

from __future__ import annotations

from app.providers.base import ProviderResponse
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.translation.engine import (
    TranslationEngine,
    TranslationSegmentInput,
    translate_via_pivot,
)
from app.translation.memory import TranslationMemoryHit

from tests.translation_fixtures import (
    FakeProvider,
    content_for,
    make_plan,
    no_sleep,
)


class FakeMemory:
    def __init__(self, hits: dict[str, TranslationMemoryHit] | None = None) -> None:
        self._hits = hits or {}
        self.stored: list[dict[str, object]] = []

    async def lookup(self, source_language: str, target_language: str, text: str):
        return self._hits.get(text)

    async def store(self, **kwargs):
        self.stored.append(kwargs)
        return None


def _engine() -> TranslationEngine:
    return TranslationEngine(sleep=no_sleep())


def _segments(*texts: str) -> list[TranslationSegmentInput]:
    return [TranslationSegmentInput(id=f"s{i}", text=text) for i, text in enumerate(texts)]


async def test_translates_and_preserves_placeholders() -> None:
    provider = FakeProvider()
    outcome = await _engine().translate(
        make_plan(), _segments("Hello world", "Visit https://example.com now"), provider=provider
    )
    assert outcome.failed == 0
    assert outcome.translations["s0"] == "TR::Hello world"
    assert "https://example.com" in outcome.translations["s1"]
    assert "\ue000" not in outcome.translations["s1"]


async def test_batching_respects_plan_size() -> None:
    provider = FakeProvider()
    plan = make_plan(batch_size=2)
    outcome = await _engine().translate(plan, _segments("a", "b", "c", "d", "e"), provider=provider)
    assert provider.calls == 3
    assert outcome.usage.input_tokens == 30  # 10 per call
    assert outcome.usage.output_tokens == 60


async def test_missing_segment_fails_without_fabricating() -> None:
    def builder(request) -> ProviderResponse:
        return ProviderResponse(
            content=content_for([{"segment_id": "s0", "translation": "only one"}])
        )

    outcome = await _engine().translate(
        make_plan(), _segments("a", "b"), provider=FakeProvider(response_builder=builder)
    )
    # The returned segment succeeds; the omitted one fails on its own rather
    # than being silently dropped or having a translation fabricated for it.
    assert outcome.translations == {"s0": "only one"}
    assert outcome.failed == 1
    assert outcome.results[1].error_category == "empty_translation"


async def test_unknown_segment_id_is_ignored_and_duplicates_fail() -> None:
    def unknown(request) -> ProviderResponse:
        return ProviderResponse(
            content=content_for(
                [
                    {"segment_id": "s0", "translation": "a"},
                    {"segment_id": "zz", "translation": "b"},
                ]
            )
        )

    # A stray id must not fail the whole batch; the real segment still lands.
    outcome = await _engine().translate(
        make_plan(), _segments("a"), provider=FakeProvider(response_builder=unknown)
    )
    assert outcome.translations == {"s0": "a"}
    assert outcome.failed == 0

    def duplicate(request) -> ProviderResponse:
        return ProviderResponse(
            content=content_for(
                [
                    {"segment_id": "s0", "translation": "a"},
                    {"segment_id": "s0", "translation": "b"},
                ]
            )
        )

    failed = await _engine().translate(
        make_plan(), _segments("a"), provider=FakeProvider(response_builder=duplicate)
    )
    assert failed.failed == 1
    assert failed.results[0].error_category == "invalid_response"


async def test_retryable_errors_are_retried() -> None:
    provider = FakeProvider(fail_first=2)
    outcome = await _engine().translate(make_plan(), _segments("a"), provider=provider)
    assert provider.calls == 3
    assert outcome.failed == 0
    assert outcome.results[0].attempts == 3


async def test_permanent_errors_are_not_retried() -> None:
    provider = FakeProvider(errors=[ProviderError(ProviderErrorCategory.AUTHENTICATION)])
    outcome = await _engine().translate(make_plan(), _segments("a"), provider=provider)
    assert provider.calls == 1
    assert outcome.failed == 1
    assert outcome.results[0].error_category == "authentication_error"


async def test_memory_hit_skips_provider() -> None:
    provider = FakeProvider()
    memory = FakeMemory({"Hello": TranslationMemoryHit(entry_id="m1", translation="سلام")})
    outcome = await _engine().translate(
        make_plan(), _segments("Hello", "New text"), provider=provider, memory=memory
    )
    assert outcome.memory_hits == 1
    assert provider.calls == 1  # only the non-memory segment
    assert outcome.results[0].source == "translation_memory"
    assert outcome.translations["s0"] == "سلام"


async def test_persist_memory_uses_source_text() -> None:
    memory = FakeMemory()
    await _engine().translate(
        make_plan(), _segments("Hello"), provider=FakeProvider(), memory=memory, persist_memory=True
    )
    assert memory.stored and memory.stored[0]["source_text"] == "Hello"


async def test_dropped_placeholder_fails_validation() -> None:
    def builder(request) -> ProviderResponse:
        return ProviderResponse(
            content=content_for([{"segment_id": "s0", "translation": "no url"}])
        )

    outcome = await _engine().translate(
        make_plan(),
        _segments("Visit https://example.com"),
        provider=FakeProvider(response_builder=builder),
    )
    assert outcome.failed == 1
    assert outcome.results[0].error_category == "validation_failed"


async def test_normalization_is_applied() -> None:
    provider = FakeProvider(transform=lambda text: text + "    extra")
    plan = make_plan(normalization={"steps": ["collapse_whitespace"]})
    outcome = await _engine().translate(plan, _segments("Hello"), provider=provider)
    assert outcome.translations["s0"] == "Hello extra"


async def test_fallback_provider_is_used() -> None:
    primary = FakeProvider(errors=[ProviderError(ProviderErrorCategory.AUTHENTICATION)])
    fallback = FakeProvider()
    outcome = await _engine().translate(
        make_plan(), _segments("Hello"), provider=primary, fallback=(fallback, "alt-model")
    )
    assert outcome.failed == 0
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_empty_segments() -> None:
    outcome = await _engine().translate(make_plan(), [], provider=FakeProvider())
    assert outcome.translations == {} and outcome.results == []


async def test_pivot_translate_composes_two_passes() -> None:
    first = FakeProvider(transform=lambda text: "DE::" + text)
    second = FakeProvider(transform=lambda text: "FA::" + text)
    outcome = await translate_via_pivot(
        _engine(),
        _segments("Hello"),
        first_plan=make_plan(target="de", target_direction="ltr", target_script="Latn"),
        first_provider=first,
        second_plan=make_plan(source="de", target="fa"),
        second_provider=second,
    )
    assert outcome.translations["s0"] == "FA::DE::Hello"
