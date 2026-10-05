"""Safe file/archive handling for document processing.

Untrusted uploads are treated as hostile: archives are inspected for path
traversal, symlinks, entry-count/size/compression limits before any member is
read. Temporary files always live under a managed temp directory and are
cleaned up.
"""

from __future__ import annotations

import hashlib
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from app.exceptions import DocumentCorruptedError, ValidationError

EPUB_MIMETYPE = "application/epub+zip"


class DocumentKind(StrEnum):
    EPUB = "epub"
    PDF = "pdf"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_entries: int = 5000
    max_compression_ratio: float = 200.0


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    size: int
    compress_size: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_kind(filename: str, header: bytes) -> DocumentKind:
    """Classify by content first, extension second."""
    if header.startswith(b"%PDF"):
        return DocumentKind.PDF
    if header[:4] == b"PK\x03\x04":
        # A zip container; EPUB is distinguished by extension/mimetype.
        if filename.lower().endswith(".epub"):
            return DocumentKind.EPUB
        return DocumentKind.UNKNOWN
    if filename.lower().endswith(".epub"):
        return DocumentKind.EPUB
    if filename.lower().endswith(".pdf"):
        return DocumentKind.PDF
    return DocumentKind.UNKNOWN


def safe_member_name(name: str) -> str:
    """Validate a zip member name; reject traversal and absolute paths."""
    if not name or name.startswith("/") or name.startswith("\\"):
        raise ValidationError("Archive contains an absolute path.")
    if "\\" in name:
        raise ValidationError("Archive contains a backslash path.")
    raw_parts = name.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise ValidationError("Archive contains a path traversal entry.")
    return str(PurePosixPath(name))


def inspect_archive(path: Path, limits: ArchiveLimits) -> list[ArchiveEntry]:
    """Validate a zip/EPUB archive and return its safe file entries."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DocumentCorruptedError("The archive is malformed.") from exc

    entries: list[ArchiveEntry] = []
    total_uncompressed = 0
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            safe_member_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValidationError("Archive contains a symbolic link.")
            if info.file_size > limits.max_uncompressed_bytes:
                raise ValidationError("Archive entry exceeds the size limit.")
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > limits.max_compression_ratio:
                    raise ValidationError("Archive compression ratio is suspicious.")
            total_uncompressed += info.file_size
            entries.append(
                ArchiveEntry(
                    name=info.filename, size=info.file_size, compress_size=info.compress_size
                )
            )
            if len(entries) > limits.max_entries:
                raise ValidationError("Archive contains too many entries.")
        if total_uncompressed > limits.max_uncompressed_bytes:
            raise ValidationError("Archive uncompressed size exceeds the limit.")
    return entries


def read_member(archive: zipfile.ZipFile, name: str, *, max_bytes: int) -> bytes:
    """Read one archive member with a hard size ceiling."""
    with archive.open(name) as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationError("Archive member exceeds the size limit.")
    return data


def verify_epub_mimetype(archive: zipfile.ZipFile, *, max_bytes: int = 4096) -> None:
    try:
        mimetype = read_member(archive, "mimetype", max_bytes=max_bytes)
    except KeyError as exc:
        raise DocumentCorruptedError("Not a valid EPUB (missing mimetype).") from exc
    if mimetype.decode("ascii", errors="ignore").strip() != EPUB_MIMETYPE:
        raise DocumentCorruptedError("Not a valid EPUB (bad mimetype).")


@contextmanager
def safe_temp_dir(*, base: Path | None = None) -> Iterator[Path]:
    """Managed temporary directory, always cleaned up."""
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="book-fork-", dir=str(base) if base else None) as tmp:
        yield Path(tmp)
