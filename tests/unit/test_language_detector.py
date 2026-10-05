"""Language detection abstraction."""

from __future__ import annotations

import pytest
from app.language.detector import LangidDetector


async def test_detects_latin_and_non_latin() -> None:
    detector = LangidDetector()
    english = await detector.detect("This is a simple English sentence about translation.")
    persian = await detector.detect("این یک جمله ساده فارسی درباره ترجمه است.")
    japanese = await detector.detect("これは翻訳に関する簡単な日本語の文です。")
    assert english is not None and english.language == "en"
    assert persian is not None and persian.language == "fa"
    assert japanese is not None and japanese.language == "ja"


async def test_short_text_returns_none() -> None:
    detector = LangidDetector()
    assert await detector.detect("hi") is None


async def test_candidates_are_ranked_and_normalized() -> None:
    detector = LangidDetector()
    result = await detector.detect("Das ist ein einfacher deutscher Satz über Übersetzung.")
    assert result is not None
    assert result.language == "de"
    assert 0.0 < result.confidence <= 1.0
    assert result.candidates
    assert result.candidates[0].language == result.language


async def test_allowed_languages_constrains_candidates() -> None:
    detector = LangidDetector(allowed_languages=["fa", "en"])
    result = await detector.detect("Das ist ein deutscher Satz über Übersetzung.")
    if result is not None:
        assert result.language in {"fa", "en"}


@pytest.mark.parametrize("language", ["en", "fa", "de"])
async def test_confidence_is_probability(language: str) -> None:
    samples: dict[str, str] = {
        "en": "The quick brown fox jumps over the lazy dog many times.",
        "fa": "روباه قهوه‌ای سریع از روی سگ تنبل می‌پرد.",
        "de": "Der schnelle braune Fuchs springt über den faulen Hund.",
    }
    detector = LangidDetector()
    result = await detector.detect(samples[language])
    assert result is not None
    total = sum(candidate.confidence for candidate in result.candidates)
    assert total == pytest.approx(1.0, abs=0.01)
