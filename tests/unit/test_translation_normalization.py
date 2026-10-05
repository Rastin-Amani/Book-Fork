"""Configurable, placeholder-safe normalization."""

from __future__ import annotations

import pytest
from app.documents.placeholders import PlaceholderProtector
from app.exceptions import ConfigurationError
from app.translation.normalization import build_normalization_pipeline


def test_nfkc_and_collapse() -> None:
    pipeline = build_normalization_pipeline({"steps": ["unicode_nfkc", "collapse_whitespace"]})
    protector = PlaceholderProtector()
    assert pipeline.normalize("ａ  b\t\tc", protector=protector) == "a b c"  # noqa: RUF001 - NFKC test


def test_empty_pipeline_is_identity() -> None:
    pipeline = build_normalization_pipeline({})
    assert (
        pipeline.normalize("unchanged  text", protector=PlaceholderProtector()) == "unchanged  text"
    )


def test_protected_content_is_not_corrupted() -> None:
    pipeline = build_normalization_pipeline({"steps": ["unicode_nfkc", "collapse_whitespace"]})
    protector = PlaceholderProtector()
    text = "See https://ex.com/a  b and <em>keep</em> this"
    result = pipeline.normalize(text, protector=protector)
    assert "https://ex.com/a" in result
    assert "<em>keep</em>" in result


def test_unknown_step_rejected() -> None:
    with pytest.raises(ConfigurationError):
        build_normalization_pipeline({"steps": ["non_existent"]})


def test_none_step_is_noop() -> None:
    pipeline = build_normalization_pipeline({"steps": ["none"]})
    assert pipeline.step_names == []
