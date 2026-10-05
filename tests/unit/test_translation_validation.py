"""Validation pipeline: placeholders, empty result, plausibility, glossary."""

from __future__ import annotations

from app.documents.placeholders import PlaceholderProtector
from app.translation.glossary import GlossaryMatch
from app.translation.validation import TranslationValidator


def _validator() -> tuple[TranslationValidator, PlaceholderProtector]:
    protector = PlaceholderProtector()
    return TranslationValidator(protector), protector


def test_valid_translation_passes() -> None:
    validator, _ = _validator()
    report = validator.validate(segment_id="s1", translated_text="نص جيد", placeholder_mapping={})
    assert report.passed
    assert report.restored == "نص جيد"


def test_empty_result_fails_hard() -> None:
    validator, _ = _validator()
    report = validator.validate(segment_id="s1", translated_text="   ", placeholder_mapping={})
    assert not report.passed


def test_dropped_placeholder_fails() -> None:
    validator, protector = _validator()
    protected = protector.protect("Visit https://ex.com now")
    # Translator dropped the URL token.
    report = validator.validate(
        segment_id="s1",
        translated_text="زور دې کتنې",
        placeholder_mapping=protected.mapping,
    )
    assert not report.passed
    assert any(issue.code == "placeholder_dropped" for issue in report.issues)


def test_placeholder_returned_as_literal_value_passes() -> None:
    validator, protector = _validator()
    protected = protector.protect("Contact rework@37signals.com today")
    # The model returned the real email instead of the protected token.
    translated = protected.text
    for token, value in protected.mapping.items():
        translated = translated.replace(token, value)
    report = validator.validate(
        segment_id="s1",
        translated_text=translated,
        placeholder_mapping=protected.mapping,
    )
    assert report.passed
    assert "rework@37signals.com" in report.restored


def test_restored_placeholder_is_available() -> None:
    validator, protector = _validator()
    protected = protector.protect("Visit https://ex.com now")
    translated = protected.text.replace("Visit", "بازدید").replace("now", "کنید")
    report = validator.validate(
        segment_id="s1",
        translated_text=translated,
        placeholder_mapping=protected.mapping,
    )
    assert report.passed
    assert "https://ex.com" in report.restored


def test_rtl_plausibility_is_soft() -> None:
    validator, _ = _validator()
    report = validator.validate(
        segment_id="s1",
        translated_text="totally latin text",
        placeholder_mapping={},
        target_direction="rtl",
    )
    assert report.passed  # soft warning, not a hard failure
    assert any(issue.code == "rtl_expected" for issue in report.warnings)


def test_glossary_terminology_soft_and_strict() -> None:
    validator, _ = _validator()
    matches = [GlossaryMatch(source_term="framework", target_term="چارچوب", preferred=True)]
    soft = validator.validate(
        segment_id="s1",
        translated_text="متن بدون اصطلاح",
        placeholder_mapping={},
        glossary_matches=matches,
    )
    assert soft.passed and soft.warnings

    strict = validator.validate(
        segment_id="s1",
        translated_text="متن بدون اصطلاح",
        placeholder_mapping={},
        glossary_matches=matches,
        validation_profile={"strict_glossary": True},
    )
    assert not strict.passed
