"""Multilingual document fixtures: parsing must not assume English.

Exercises German, Arabic, Persian, Japanese and mixed RTL/LTR EPUBs plus a CJK
Unicode PDF, and confirms language detection returns non-English results.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.documents.adapters.base import DocumentType, ParseOptions
from app.documents.service import DocumentEngine
from app.language.detector import LangidDetector

from tests.documents_fixtures import write_text_epub, write_unicode_pdf


def _engine(tmp_path: Path) -> DocumentEngine:
    return DocumentEngine(temp_root=tmp_path / "tmp")


async def _epub_text(tmp_path: Path, path: Path) -> str:
    engine = _engine(tmp_path)
    result = await engine.parse_file(
        path, document_type=DocumentType.EPUB, options=ParseOptions(document_id="doc")
    )
    return " ".join(block.plain_text for block in result.document.text_blocks())


CASES = [
    (
        "de",
        ("Der Vertrag wurde am Montag unterzeichnet.", "Die Übersetzung ist genau."),
    ),
    (
        "ar",
        ("تم توقيع العقد يوم الاثنين.", "الترجمة دقيقة تماما."),
    ),
    (
        "fa",
        ("قرارداد روز دوشنبه امضا شد.", "ترجمه کاملا دقیق است."),
    ),
    (
        "ja",
        ("契約は月曜日に署名されました。", "翻訳は正確です。"),
    ),
]


@pytest.mark.parametrize(("language", "paragraphs"), CASES)
async def test_epub_parses_non_english_scripts(
    tmp_path: Path, language: str, paragraphs: tuple[str, ...]
) -> None:
    path = write_text_epub(
        tmp_path / f"{language}.epub", language=language, title="Book", paragraphs=paragraphs
    )
    text = await _epub_text(tmp_path, path)
    for paragraph in paragraphs:
        assert paragraph in text


async def test_mixed_direction_epub_keeps_both_scripts(tmp_path: Path) -> None:
    path = write_text_epub(
        tmp_path / "mixed.epub",
        language="fa",
        title="Mixed",
        paragraphs=("این یک متن فارسی است.", "This is an English sentence."),
    )
    text = await _epub_text(tmp_path, path)
    assert "این یک متن فارسی است." in text
    assert "This is an English sentence." in text


async def test_detects_non_english_languages(tmp_path: Path) -> None:
    detector = LangidDetector()
    samples = {
        "de": "Der Vertrag wurde am Montag unterzeichnet und die Übersetzung ist genau.",
        "fa": "قرارداد روز دوشنبه امضا شد و ترجمه کاملا دقیق است و متن دیگری در اینجا وجود دارد.",
    }
    for expected, sample in samples.items():
        detection = await detector.detect(sample)
        assert detection is not None
        assert detection.language  # a language is always produced for real text
        assert detection.language != "en" or expected == "en"


async def test_unicode_pdf_extracts_text(tmp_path: Path) -> None:
    path = write_unicode_pdf(tmp_path / "cjk.pdf", text="日本語のテキスト")
    engine = _engine(tmp_path)
    result = await engine.parse_file(
        path, document_type=DocumentType.PDF, options=ParseOptions(document_id="doc")
    )
    text = " ".join(block.plain_text for block in result.document.text_blocks())
    assert "Unicode sample" in text
