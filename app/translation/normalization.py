"""Configurable text normalization.

Normalization is selected by target-language configuration; nothing language
specific is hardcoded. Protected strings (placeholders, URLs, markup, code) are
shielded during normalization so they are never corrupted.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.documents.placeholders import PlaceholderProtector
from app.exceptions import ConfigurationError

_COLLAPSE = re.compile(r"[ \t\u00a0]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _collapse_whitespace(text: str) -> str:
    return _COLLAPSE.sub(" ", text)


def _strip_control(text: str) -> str:
    return _CONTROL.sub("", text)


_STEPS: dict[str, Callable[[str], str]] = {
    "unicode_nfkc": _nfkc,
    "collapse_whitespace": _collapse_whitespace,
    "strip_control": _strip_control,
    "none": lambda text: text,
}


@dataclass(frozen=True, slots=True)
class NormalizationStep:
    name: str
    options: Mapping[str, Any]


class TextNormalizationPipeline:
    def __init__(self, steps: Sequence[NormalizationStep]) -> None:
        self._steps = tuple(steps)

    @property
    def step_names(self) -> list[str]:
        return [step.name for step in self._steps]

    def normalize(self, text: str, *, protector: PlaceholderProtector) -> str:
        """Normalize text without corrupting protected substrings."""
        if not self._steps:
            return text
        guarded = protector.protect(text)
        result = guarded.text
        for step in self._steps:
            processor = _STEPS.get(step.name)
            if processor is None:
                raise ConfigurationError(f"Unknown normalization step {step.name!r}.")
            result = processor(result)
        return protector.restore(result, guarded.mapping)


def build_normalization_pipeline(config: Mapping[str, Any] | None) -> TextNormalizationPipeline:
    """Build a pipeline from a configuration mapping (e.g. profile/language)."""
    if not config:
        return TextNormalizationPipeline(())
    raw_steps = config.get("steps", [])
    steps: list[NormalizationStep] = []
    for raw in raw_steps:
        if isinstance(raw, str):
            name, options = raw, {}
        elif isinstance(raw, Mapping):
            name = str(raw.get("type", ""))
            options = {k: v for k, v in raw.items() if k != "type"}
        else:
            raise ConfigurationError("Invalid normalization pipeline configuration.")
        if name == "none":
            continue
        if name not in _STEPS:
            raise ConfigurationError(f"Unknown normalization step {name!r}.")
        steps.append(NormalizationStep(name=name, options=options))
    return TextNormalizationPipeline(steps)
