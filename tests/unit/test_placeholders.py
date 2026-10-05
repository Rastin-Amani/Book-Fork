"""Placeholder protection and restoration."""

from __future__ import annotations

from app.documents.placeholders import PlaceholderProtector


def test_protects_urls_emails_markup() -> None:
    protector = PlaceholderProtector()
    result = protector.protect(
        "See https://example.com/a or email a@b.co. Use <em>emphasis</em> and `code`."
    )
    assert "https://example.com/a" not in result.text
    assert "a@b.co" not in result.text
    assert "<em>" not in result.text
    assert protector.has_tokens(result.text)
    assert set(result.mapping.values()) >= {"https://example.com/a", "a@b.co", "<em>"}


def test_restore_is_lossless() -> None:
    protector = PlaceholderProtector()
    original = "Link [x](https://e.co) and {{ variable }} and <b>bold</b>."
    protected = protector.protect(original)
    assert protector.restore(protected.text, protected.mapping) == original


def test_noop_when_nothing_to_protect() -> None:
    protector = PlaceholderProtector()
    result = protector.protect("Just plain prose here.")
    assert result.text == "Just plain prose here."
    assert result.mapping == {}


def test_restore_with_empty_mapping() -> None:
    protector = PlaceholderProtector()
    assert protector.restore("text", {}) == "text"


def test_placeholders_survive_translation_roundtrip() -> None:
    protector = PlaceholderProtector()
    protected = protector.protect("Visit https://example.com now.")
    # A translator would preserve the opaque token; simulate that.
    translated = protected.text.replace("Visit", "بازدید").replace("now", "کنید")
    restored = protector.restore(translated, protected.mapping)
    assert "https://example.com" in restored
    assert "بازدید" in restored
