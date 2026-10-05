"""Language tag normalization and metadata derivation (data-driven)."""

from __future__ import annotations

import pytest
from app.exceptions import ValidationError
from app.language.models import Direction
from app.language.normalize import normalize_tag


def test_rtl_derived_from_data_not_a_hardcoded_list() -> None:
    assert normalize_tag("fa").direction is Direction.RTL
    assert normalize_tag("ar").direction is Direction.RTL
    assert normalize_tag("he").direction is Direction.RTL
    assert normalize_tag("ur").direction is Direction.RTL


def test_ltr_languages() -> None:
    assert normalize_tag("en").direction is Direction.LTR
    assert normalize_tag("de").direction is Direction.LTR
    assert normalize_tag("ja").direction is Direction.LTR


@pytest.mark.parametrize(
    ("tag", "language", "region", "script"),
    [
        ("en", "en", None, "Latn"),
        ("en-US", "en", "US", "Latn"),
        ("pt-BR", "pt", "BR", "Latn"),
        ("pt-PT", "pt", "PT", "Latn"),
        ("fa-IR", "fa", "IR", "Arab"),
        ("zh-CN", "zh", "CN", "Hans"),
        ("zh-TW", "zh", "TW", "Hant"),
        ("hy", "hy", None, "Armn"),
    ],
)
def test_normalization(tag: str, language: str, region: str | None, script: str) -> None:
    normalized = normalize_tag(tag)
    assert normalized.language == language
    assert normalized.region == region
    assert normalized.script == script


def test_names_derived_from_cldr() -> None:
    assert normalize_tag("fa").name == "Persian"
    assert normalize_tag("pt-BR").name.startswith("Portuguese")
    assert normalize_tag("fa").native_name


@pytest.mark.parametrize("tag", ["", "   ", "!!not-a-tag!!"])
def test_invalid_tags_rejected(tag: str) -> None:
    with pytest.raises(ValidationError):
        normalize_tag(tag)
