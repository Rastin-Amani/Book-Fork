"""Placeholder protection for non-translatable content.

URLs, emails, markup, template syntax and inline code must never be entrusted
to an LLM instruction alone. They are replaced with opaque tokens before
translation and restored afterwards.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_TOKEN_OPEN = "\ue000"
_TOKEN_CLOSE = "\ue001"

# Order matters: more specific/longer constructs first so a URL inside a
# markdown link is not protected separately.
_DEFAULT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("html_tag", re.compile(r"<[^>]+>")),
    ("markdown_image", re.compile(r"!\[[^\]]*\]\([^)]+\)")),
    ("markdown_link", re.compile(r"\[[^\]]+\]\([^)]+\)")),
    ("template_block", re.compile(r"\{%.*?%\}")),
    ("template_var", re.compile(r"\{\{.*?\}\}")),
    ("code_span", re.compile(r"`[^`]+`")),
    ("url", re.compile(r"https?://[^\s<>\"')]+")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    (
        "uuid",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ProtectedText:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)


class PlaceholderProtector:
    """Protects and restores non-translatable substrings."""

    def __init__(
        self,
        patterns: Sequence[tuple[str, re.Pattern[str]]] | None = None,
        *,
        token_label: str = "ph",
        max_placeholders: int = 2000,
    ) -> None:
        self._patterns = tuple(patterns) if patterns is not None else _DEFAULT_PATTERNS
        self._label = token_label
        self._max = max_placeholders

    def _token(self, index: int) -> str:
        return f"{_TOKEN_OPEN}{self._label}{index}{_TOKEN_CLOSE}"

    def protect(self, text: str) -> ProtectedText:
        mapping: dict[str, str] = {}
        protected = text

        for _name, pattern in self._patterns:
            if len(mapping) >= self._max:
                break

            def replace(match: re.Match[str], mapping: dict[str, str] = mapping) -> str:
                token = self._token(len(mapping))
                mapping[token] = match.group(0)
                return token

            protected = pattern.sub(replace, protected)

        return ProtectedText(text=protected, mapping=mapping)

    def restore(self, text: str, mapping: dict[str, str]) -> str:
        if not mapping:
            return text

        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            return mapping.get(token, token)

        token_pattern = re.compile(re.escape(_TOKEN_OPEN) + r".*?" + re.escape(_TOKEN_CLOSE))
        return token_pattern.sub(replace, text)

    @staticmethod
    def has_tokens(text: str) -> bool:
        return _TOKEN_OPEN in text
