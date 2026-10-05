"""Language detection abstraction.

Auto-detection is advisory: a user selection always overrides the detected
language. The default detector (``py3langid``) is lightweight and fully offline;
it can be swapped for another provider behind this interface.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import anyio
import py3langid

_MAX_TEXT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    language: str
    confidence: float


@dataclass(frozen=True, slots=True)
class DetectionResult:
    language: str
    confidence: float
    candidates: list[DetectionCandidate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LanguageDetector(Protocol):
    """Detects the language of a block of text."""

    async def detect(self, text: str) -> DetectionResult | None:
        """Return a detection result, or ``None`` if text is too short/unknown."""
        ...


def _softmax(scores: list[tuple[str, float]]) -> list[DetectionCandidate]:
    if not scores:
        return []
    top = max(score for _, score in scores)
    exps = [(lang, math.exp(score - top)) for lang, score in scores]
    total = sum(value for _, value in exps) or 1.0
    return [DetectionCandidate(language=lang, confidence=value / total) for lang, value in exps]


class LangidDetector:
    """Broad multilingual detector backed by py3langid (offline)."""

    name = "py3langid"

    def __init__(
        self,
        *,
        allowed_languages: Sequence[str] | None = None,
        max_candidates: int = 5,
    ) -> None:
        self._allowed = {lang.lower() for lang in allowed_languages} if allowed_languages else None
        self._max_candidates = max_candidates

    async def detect(self, text: str) -> DetectionResult | None:
        sample = text.strip()[:_MAX_TEXT_CHARS]
        if len(sample) < 8:
            return None
        # py3langid is synchronous/CPU-bound; keep it off the event loop.
        ranked = await anyio.to_thread.run_sync(self._rank, sample)
        if not ranked:
            return None
        candidates = _softmax(ranked)
        if not candidates:
            return None
        best = candidates[0]
        return DetectionResult(
            language=best.language,
            confidence=best.confidence,
            candidates=candidates[: self._max_candidates],
            metadata={"detector": self.name},
        )

    def _rank(self, sample: str) -> list[tuple[str, float]]:
        ranked: list[tuple[str, float]] = py3langid.rank(sample)
        if self._allowed is not None:
            ranked = [(lang, score) for lang, score in ranked if lang.lower() in self._allowed]
        return ranked[: self._max_candidates * 3]
