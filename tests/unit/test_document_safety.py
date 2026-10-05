"""Archive/file safety and limits."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from app.documents.safety import (
    ArchiveLimits,
    DocumentKind,
    inspect_archive,
    safe_member_name,
    safe_temp_dir,
    sha256_bytes,
    sha256_file,
    sniff_kind,
)
from app.exceptions import DocumentCorruptedError, ValidationError

from tests.documents_fixtures import (
    write_epub,
    write_malformed_epub,
    write_traversal_zip,
    write_zip_bomb,
)


def test_sniff_kind() -> None:
    assert sniff_kind("a.pdf", b"%PDF-1.7") is DocumentKind.PDF
    assert sniff_kind("a.epub", b"PK\x03\x04") is DocumentKind.EPUB
    assert sniff_kind("a.bin", b"\x00\x01") is DocumentKind.UNKNOWN


def test_checksums(tmp_path: Path) -> None:
    data = b"hello world"
    assert sha256_bytes(data) == sha256_bytes(data)
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    assert sha256_file(path) == sha256_bytes(data)


def test_valid_epub_inspection(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "ok.epub")
    entries = inspect_archive(path, ArchiveLimits())
    assert any(entry.name == "OEBPS/content.opf" for entry in entries)


def test_malformed_zip_rejected(tmp_path: Path) -> None:
    path = write_malformed_epub(tmp_path / "bad.epub")
    with pytest.raises(DocumentCorruptedError):
        inspect_archive(path, ArchiveLimits())


def test_path_traversal_rejected(tmp_path: Path) -> None:
    path = write_traversal_zip(tmp_path / "evil.epub")
    with pytest.raises(ValidationError):
        inspect_archive(path, ArchiveLimits())


def test_zip_bomb_ratio_rejected(tmp_path: Path) -> None:
    path = write_zip_bomb(tmp_path / "bomb.epub")
    with pytest.raises(ValidationError):
        inspect_archive(path, ArchiveLimits(max_compression_ratio=10.0))


def test_entry_count_limit(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "ok.epub")
    with pytest.raises(ValidationError):
        inspect_archive(path, ArchiveLimits(max_entries=1))


def test_safe_member_name() -> None:
    assert safe_member_name("OEBPS/chapter.xhtml") == "OEBPS/chapter.xhtml"
    for bad in ["/etc/passwd", "../evil", "a/../../b", "a\\b", "./a"]:
        with pytest.raises(ValidationError):
            safe_member_name(bad)


def test_temp_dir_is_cleaned_up() -> None:
    with safe_temp_dir() as tmp:
        marker = tmp / "x"
        marker.write_text("data")
        captured = tmp
    assert not captured.exists()


def test_zipfile_bad_archive(tmp_path: Path) -> None:
    path = tmp_path / "not.zip"
    path.write_bytes(b"nope")
    with pytest.raises(DocumentCorruptedError):
        inspect_archive(path, ArchiveLimits())
    # sanity: a real zip opens
    good = write_epub(tmp_path / "good.epub")
    with zipfile.ZipFile(good) as archive:
        assert archive.read("mimetype") == b"application/epub+zip"
