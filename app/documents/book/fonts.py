"""Book typography: bundled fonts and per-script selection.

Persian/Arabic-script books use **Vazirmatn** (designed for Persian). Latin,
Greek and Cyrillic books use **Crimson Text** (a classic book serif). Both are
SIL OFL and shipped with the application so output embeds correctly everywhere,
including environments with no system fonts.

Additional scripts can be supplied (Google "Noto Serif" family) by dropping
``.ttf`` files into ``DOCUMENT_FONT_DIR``; they are registered as extra faces
and used for scripts the bundled fonts do not cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BUNDLED_FONT_DIR = Path(__file__).parent / "fonts"

# Arabic-script languages (right-to-left). Used when the plan does not carry an
# explicit ISO 15924 script.
_LANGUAGE_SCRIPTS = {
    "fa": "Arab",
    "ar": "Arab",
    "ur": "Arab",
    "ps": "Arab",
    "ku": "Arab",
    "ckb": "Arab",
    "sd": "Arab",
    "ug": "Arab",
    "yi": "Hebr",
    "he": "Hebr",
    "dv": "Thaa",
}

# ISO 15924 script -> bundled family stem. Scripts without a bundled family can
# still be mapped to a Google "Noto Serif" family that an admin places in
# DOCUMENT_FONT_DIR (see docs/documents.md).
_SCRIPT_FAMILIES = {
    "Arab": "Vazirmatn",
    "Thaa": "Vazirmatn",
    "Latn": "CrimsonText",
    "Cyrl": "CrimsonText",
    "Grek": "CrimsonText",
    "Hebr": "NotoSerifHebrew",
    "Deva": "NotoSerifDevanagari",
    "Beng": "NotoSerifBengali",
    "Thai": "NotoSerifThai",
    "Armn": "NotoSerifArmenian",
    "Geor": "NotoSerifGeorgian",
    "Ethi": "NotoSerifEthiopic",
    "Hani": "NotoSerifCJKsc",
    "Jpan": "NotoSerifCJKjp",
    "Kore": "NotoSerifCJKkr",
}

_DEFAULT_FAMILY = "CrimsonText"
_BUNDLED_FAMILIES = {"Vazirmatn", "CrimsonText"}

# Files that make up each family. Extra families use a simple convention so an
# admin can install them without code changes.
_FAMILY_FILES: dict[str, dict[str, str]] = {
    "Vazirmatn": {
        "normal": "Vazirmatn-Regular.ttf",
        "bold": "Vazirmatn-Bold.ttf",
    },
    "CrimsonText": {
        "normal": "CrimsonText-Regular.ttf",
        "bold": "CrimsonText-Bold.ttf",
        "italic": "CrimsonText-Italic.ttf",
        "bold_italic": "CrimsonText-BoldItalic.ttf",
    },
}


def _family_files(family: str) -> dict[str, str]:
    """File names for a family (bundled explicitly, extra by convention)."""
    if family in _FAMILY_FILES:
        return _FAMILY_FILES[family]
    return {
        "normal": f"{family}-Regular.ttf",
        "bold": f"{family}-Bold.ttf",
        "italic": f"{family}-Italic.ttf",
    }


@dataclass(frozen=True, slots=True)
class BookFont:
    """The primary family for a book plus resolved face file paths."""

    family: str
    regular: Path
    bold: Path
    italic: Path | None = None
    bold_italic: Path | None = None

    def path_for(self, *, bold: bool = False, italic: bool = False) -> Path:
        if bold and italic and self.bold_italic:
            return self.bold_italic
        if italic and self.italic:
            return self.italic
        return self.bold if bold else self.regular

    def family_stack(self) -> str:
        """A CSS font-family list: chosen family, then bundled fallbacks."""
        others = [name for name in _FAMILY_FILES if name != self.family]
        fallbacks = ", ".join(f"'{name}'" for name in others)
        return f"'{self.family}', {fallbacks}, serif"


def script_for_language(language: str | None, script: str | None = None) -> str | None:
    """Resolve an ISO 15924 script from an explicit value or a language tag."""
    if script:
        return script
    if not language:
        return None
    base = language.split("-", 1)[0].lower()
    return _LANGUAGE_SCRIPTS.get(base)


def book_font(
    language: str | None,
    *,
    script: str | None = None,
    font_dir: str | Path | None = None,
) -> BookFont:
    """Return the bundled book font for ``language``/``script``.

    ``font_dir`` is consulted only to find a replacement for the *chosen*
    family when an admin ships a custom face; otherwise bundled files are used.
    """
    resolved_script = script_for_language(language, script)
    family = _SCRIPT_FAMILIES.get(resolved_script or "", _DEFAULT_FAMILY)
    base = _candidate_dir(family, font_dir)
    if base is None and family in _BUNDLED_FAMILIES:
        base = BUNDLED_FONT_DIR
    if base is None:  # requested family not installed -> bundled Latin/default
        family = _DEFAULT_FAMILY
        base = _candidate_dir(family, font_dir) or BUNDLED_FONT_DIR
    files = _family_files(family)
    return BookFont(
        family=family,
        regular=base / files["normal"],
        bold=base / files["bold"],
        italic=base / files["italic"] if "italic" in files else None,
        bold_italic=base / files["bold_italic"] if "bold_italic" in files else None,
    )


def _candidate_dir(family: str, font_dir: str | Path | None) -> Path | None:
    if not font_dir:
        return None
    directory = Path(font_dir)
    if not directory.is_dir():
        return None
    files = _family_files(family)
    required = (files["normal"], files["bold"])
    if all((directory / name).is_file() for name in required):
        return directory
    return None


def font_face_css(font: BookFont, extra_dir: str | Path | None = None) -> str:
    """CSS ``@font-face`` rules for the chosen font and any extra faces."""
    faces: list[str] = []
    for weight, style, path in _face_specs(font):
        faces.append(
            f"@font-face{{font-family:'{font.family}';font-weight:{weight};"
            f"font-style:{style};src:url('{path.name}');}}"
        )
    if extra_dir:
        directory = Path(extra_dir)
        if directory.is_dir():
            for path in sorted(directory.glob("*.ttf")):
                family = path.stem.replace(" ", "")
                faces.append(f"@font-face{{font-family:'{family}';src:url('{path.name}');}}")
    return "".join(faces)


def _face_specs(font: BookFont) -> list[tuple[str, str, Path]]:
    specs: list[tuple[str, str, Path]] = [
        ("normal", "normal", font.regular),
        ("bold", "normal", font.bold),
    ]
    if font.italic:
        specs.append(("normal", "italic", font.italic))
    if font.bold_italic:
        specs.append(("bold", "italic", font.bold_italic))
    return specs


def archive_dirs(font: BookFont, extra_dir: str | Path | None = None) -> list[str]:
    """Directories an EPUB/PyMuPDF archive must search for the font files."""
    dirs: list[str] = []
    for _weight, _style, path in _face_specs(font):
        parent = str(path.parent)
        if parent not in dirs:
            dirs.append(parent)
    if extra_dir and Path(extra_dir).is_dir() and str(extra_dir) not in dirs:
        dirs.append(str(extra_dir))
    return dirs


__all__ = [
    "BUNDLED_FONT_DIR",
    "BookFont",
    "archive_dirs",
    "book_font",
    "font_face_css",
    "script_for_language",
]
