"""Translation validation pipeline.

Deterministic stages — schema (structured module), segment-id integrity
(structured module), placeholders, format, empty-result, language plausibility
and glossary terminology. LLM QA is intentionally not a mandatory stage.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.documents.placeholders import PlaceholderProtector
from app.translation.glossary import GlossaryMatch, terminology_issues


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    stage: str
    code: str
    message: str
    hard: bool = False


@dataclass(frozen=True, slots=True)
class ValidationReport:
    passed: bool
    restored: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if not issue.hard]


def _has_rtl(text: str) -> bool:
    return any(unicodedata.bidirectional(char) in {"R", "AL", "AN"} for char in text)


def _has_cjk(text: str) -> bool:
    return any("\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" for char in text)


class TranslationValidator:
    def __init__(self, protector: PlaceholderProtector) -> None:
        self._protector = protector

    def validate(
        self,
        *,
        segment_id: str,
        translated_text: str,
        placeholder_mapping: Mapping[str, str],
        target_script: str | None = None,
        target_direction: str | None = None,
        glossary_matches: Sequence[GlossaryMatch] = (),
        validation_profile: Mapping[str, object] | None = None,
    ) -> ValidationReport:
        profile = dict(validation_profile or {})
        issues: list[ValidationIssue] = []

        if not translated_text or not translated_text.strip():
            issues.append(
                ValidationIssue("empty", "empty_result", "Translator returned empty text.", True)
            )

        # Placeholder integrity: every token must survive (as the token or, when
        # the model returns the literal value, as that value), and restoration
        # must leave no token behind.
        missing = [
            token
            for token in placeholder_mapping
            if token not in translated_text and placeholder_mapping[token] not in translated_text
        ]
        if missing:
            issues.append(
                ValidationIssue(
                    "placeholder",
                    "placeholder_dropped",
                    f"{len(missing)} protected placeholder(s) were dropped.",
                    True,
                )
            )
        restored = self._protector.restore(translated_text, dict(placeholder_mapping))
        if self._protector.has_tokens(restored):
            issues.append(
                ValidationIssue(
                    "placeholder",
                    "placeholder_unrestorable",
                    "Placeholders could not be restored safely.",
                    True,
                )
            )

        # Language plausibility (soft): RTL target should contain RTL characters.
        if target_direction == "rtl" and restored.strip() and not _has_rtl(restored):
            issues.append(
                ValidationIssue(
                    "language", "rtl_expected", "Target is RTL but no RTL characters found."
                )
            )
        if (
            target_script in {"Jpan", "Hani", "Hang"}
            and restored.strip()
            and not _has_cjk(restored)
        ):
            issues.append(
                ValidationIssue(
                    "language", "script_expected", "Target script characters not detected."
                )
            )

        # Glossary terminology (soft unless strict configured).
        strict_glossary = bool(profile.get("strict_glossary", False))
        for message in terminology_issues(list(glossary_matches), restored):
            issues.append(ValidationIssue("glossary", "terminology", message, strict_glossary))

        hard = any(issue.hard for issue in issues)
        return ValidationReport(passed=not hard, restored=restored, issues=issues)
