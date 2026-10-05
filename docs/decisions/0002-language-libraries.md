# ADR 0002 — Language, locale, and detection libraries

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Phase 2 requires a generic, data-driven language system: validate and normalize
BCP-47/ISO identifiers, derive names/scripts/direction from maintained data, and
detect the language of uploaded text. The package policy requires current stable
releases compatible with Python 3.14.

## Decision

- **`langcodes` (3.5.1) + `language-data` (1.4.0)** for BCP-47 parsing,
  normalization, and language-name metadata.
- **`Babel` (2.18.0)** for CLDR locale data: display names, native names, script,
  and text direction. Direction is read from CLDR, never hardcoded.
- **`py3langid` (0.4.0)** for broad multilingual, fully offline language
  detection behind the `LanguageDetector` protocol.

## Rationale

- `langcodes`/`Babel` are the maintained, widely used sources of CLDR-backed
  language data; deriving direction from them removes the RTL/LTR list anti-
  pattern entirely.
- `py3langid` is pure-Python and offline (no model download, no network at
  inference), unlike `fast-langdetect` (downloads fastText models) and heavier
  options such as `lingua-language-detector`. This matches the project's
  low-overhead preference while still covering ~97 languages.
- The detector is abstracted (`app/language/detector.py`); `lingua` can be added
  as an alternative adapter if detection accuracy becomes the bottleneck.

## Consequences

- `py3langid` pulls in `numpy` (transitive); acceptable for a server backend.
- Language tags persist normalized as BCP-47 (`language_code`, `default_locale`)
  with ISO 639-1/639-3 where available.
- Detection is advisory: a user-selected source language always overrides the
  detected one.
