"""Translation context construction.

Builds bounded context (document, chapter, previous/next segments, glossary and
translation memory) according to a configurable policy. It never sends a whole
book to a provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.translation.plan import ContextPolicy

_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class ContextInputs:
    document_metadata: Mapping[str, Any] = field(default_factory=dict)
    section_title: str | None = None
    previous_segments: Sequence[str] = field(default_factory=tuple)
    next_segments: Sequence[str] = field(default_factory=tuple)
    user_instructions: str | None = None
    glossary_lines: Sequence[str] = field(default_factory=tuple)
    memory_lines: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class BuiltContext:
    document_context: str = ""
    chapter_context: str = ""
    previous_context: str = ""
    next_context: str = ""
    glossary_text: str = ""
    translation_memory_text: str = ""
    user_instructions: str = ""

    def as_prompt_variables(self) -> dict[str, str]:
        """Variables matching the prompt renderer's allow-list."""
        return {
            "document_context": self.document_context,
            "chapter_context": self.chapter_context,
            "previous_context": self.previous_context,
            "next_context": self.next_context,
            "glossary": self.glossary_text,
            "translation_memory": self.translation_memory_text,
        }


def _estimate_tokens(*texts: str) -> int:
    return sum(len(text) for text in texts) // _CHARS_PER_TOKEN


class TranslationContextBuilder:
    """Builds policy-compliant context for a batch of segments."""

    def build(self, policy: ContextPolicy, inputs: ContextInputs) -> BuiltContext:
        strategy = policy.strategy
        previous = list(inputs.previous_segments) if strategy != "minimal" else []
        include_next = strategy == "adaptive"
        next_segments = list(inputs.next_segments) if include_next else []

        previous = previous[-policy.max_previous_segments :] if policy.max_previous_segments else []
        next_segments = (
            next_segments[: policy.max_previous_segments] if policy.max_previous_segments else []
        )

        document_title = str(inputs.document_metadata.get("title") or "")
        parts = _split_document(inputs.document_metadata)

        document_context = document_title
        chapter_context = inputs.section_title or ""
        previous_context = "\n".join(previous)
        next_context = "\n".join(next_segments)

        if strategy == "minimal":
            chapter_context = ""
            document_context = document_title

        # Bound total context by configured token limit, dropping the least
        # important parts first (next, then previous, then document extra).
        while (
            _estimate_tokens(document_context, chapter_context, previous_context, next_context)
            > policy.max_context_tokens
        ):
            if next_context:
                next_context = ""
            elif previous_context:
                previous_context = ""
            elif document_context:
                document_context = ""
            elif parts:
                parts.pop()
            else:
                break

        return BuiltContext(
            document_context=document_context,
            chapter_context=chapter_context,
            previous_context=previous_context,
            next_context=next_context,
            glossary_text="\n".join(inputs.glossary_lines),
            translation_memory_text="\n".join(inputs.memory_lines),
            user_instructions=inputs.user_instructions or "",
        )


def _split_document(metadata: Mapping[str, Any]) -> list[str]:
    parts: list[str] = []
    authors = metadata.get("authors")
    if authors:
        parts.append("Authors: " + ", ".join(str(a) for a in authors))
    description = metadata.get("description")
    if description:
        parts.append(str(description))
    return parts
