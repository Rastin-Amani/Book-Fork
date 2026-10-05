"""Glossary retrieval and terminology checks.

Only relevant terms are retrieved (simple exact/token matching for V1 — no
vector search), and preferred terminology is validated after translation where
it is deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.repositories.knowledge import GlossaryTermRepository
from app.schemas.knowledge import GlossaryTerm


@dataclass(frozen=True, slots=True)
class GlossaryMatch:
    source_term: str
    target_term: str
    preferred: bool = False
    forbidden: bool = False
    case_sensitive: bool = False


def _matches(term: GlossaryTerm, text: str) -> bool:
    flags = 0 if term.case_sensitive else re.IGNORECASE
    if term.exact_match:
        pattern = re.compile(rf"(?<!\w){re.escape(term.source_term)}(?!\w)", flags)
        return bool(pattern.search(text))
    if term.case_sensitive:
        return term.source_term in text
    return term.source_term.lower() in text.lower()


class GlossaryRetriever:
    def __init__(
        self,
        repository: GlossaryTermRepository,
        glossary_ids: list[str],
        *,
        token: str | None = None,
    ) -> None:
        self._repository = repository
        self._glossary_ids = list(glossary_ids)
        self._token = token

    async def relevant(
        self,
        source_language: str,
        target_language: str,
        text: str,
        *,
        limit: int = 50,
    ) -> list[GlossaryMatch]:
        matches: list[GlossaryMatch] = []
        seen: set[str] = set()
        for glossary_id in self._glossary_ids:
            terms = await self._repository.list_for_pair(
                glossary_id, source_language, target_language, token=self._token
            )
            for term in terms:
                key = term.source_term.casefold()
                if key in seen or not _matches(term, text):
                    continue
                seen.add(key)
                matches.append(
                    GlossaryMatch(
                        source_term=term.source_term,
                        target_term=term.target_term,
                        preferred=term.preferred,
                        forbidden=term.forbidden,
                        case_sensitive=term.case_sensitive,
                    )
                )
                if len(matches) >= limit:
                    return matches
        return matches


def glossary_lines(matches: list[GlossaryMatch]) -> list[str]:
    lines: list[str] = []
    for match in matches:
        note = " (preferred)" if match.preferred else ""
        note += " (forbidden)" if match.forbidden else ""
        lines.append(f"{match.source_term} => {match.target_term}{note}")
    return lines


def terminology_issues(matches: list[GlossaryMatch], translated_text: str) -> list[str]:
    issues: list[str] = []
    for match in matches:
        if (
            match.forbidden
            and match.target_term
            and match.target_term.lower() in translated_text.lower()
        ):
            issues.append(f"Forbidden term used: {match.target_term!r}.")
        elif (
            match.preferred
            and match.target_term
            and match.target_term.lower() not in translated_text.lower()
        ):
            issues.append(f"Preferred term missing: {match.target_term!r}.")
    return issues
