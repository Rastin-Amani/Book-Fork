"""BCP-47 language tag normalization and metadata derivation.

Uses ``langcodes`` (with CLDR data) and ``Babel`` to validate and normalize
identifiers. No language list or direction mapping is hardcoded here — script and
direction come from CLDR data.
"""

from __future__ import annotations

from dataclasses import dataclass

from babel import Locale
from babel.core import UnknownLocaleError
from langcodes import Language as LangcodesLanguage

from app.exceptions import ValidationError
from app.language.models import Direction


@dataclass(frozen=True, slots=True)
class NormalizedLanguage:
    """Normalized language metadata derived from a tag."""

    tag: str
    language: str
    script: str | None
    region: str | None
    direction: Direction
    name: str
    native_name: str | None
    iso_639_1: str | None
    iso_639_3: str | None
    default_locale: str


def _babel_locale(language: str, region: str | None) -> Locale | None:
    candidates = [f"{language}_{region}"] if region else []
    candidates.append(language)
    for identifier in candidates:
        try:
            return Locale.parse(identifier)
        except UnknownLocaleError, ValueError:
            continue
    return None


def normalize_tag(tag: str) -> NormalizedLanguage:
    """Validate and normalize a BCP-47/ISO tag.

    Raises :class:`ValidationError` for identifiers that cannot be parsed.
    """
    cleaned = (tag or "").strip()
    if not cleaned:
        raise ValidationError("A language tag is required.")

    try:
        language = LangcodesLanguage.get(cleaned)
    except Exception as exc:
        raise ValidationError(f"Invalid language tag: {tag!r}.") from exc

    if not language.is_valid():
        raise ValidationError(f"Invalid language tag: {tag!r}.")

    maximized = language.maximize()
    code = maximized.language or language.language
    if not code:
        raise ValidationError(f"Invalid language tag: {tag!r}.")
    script = maximized.script
    region = language.territory

    locale = _babel_locale(code, region)
    if locale is not None:
        direction = Direction.RTL if locale.text_direction == "rtl" else Direction.LTR
        name = locale.get_display_name("en") or code
        native_name = locale.get_display_name(locale)
    else:
        direction = Direction.LTR
        name = language.display_name("en") or code
        native_name = None

    iso_639_1 = code if len(code) == 2 else None
    iso_639_3 = _to_alpha3(language)
    default_locale = f"{code}-{region}" if region else code

    return NormalizedLanguage(
        tag=maximized.to_tag(),
        language=code,
        script=script,
        region=region,
        direction=direction,
        name=name,
        native_name=native_name,
        iso_639_1=iso_639_1,
        iso_639_3=iso_639_3,
        default_locale=default_locale,
    )


def _to_alpha3(language: LangcodesLanguage) -> str | None:
    try:
        return str(language.to_alpha3())
    except Exception:
        lang_code = language.language or ""
        return lang_code if len(lang_code) == 3 else None
