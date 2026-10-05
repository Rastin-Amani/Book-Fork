"""Glossary retrieval and terminology checks."""

from __future__ import annotations

from app.repositories.knowledge import GlossaryTermRepository
from app.translation.glossary import (
    GlossaryRetriever,
    glossary_lines,
    terminology_issues,
)


def _seed(fake_pb, glossary_id: str = "g1") -> None:
    fake_pb.seed("glossaries", {"id": glossary_id, "workspace": "w1", "name": "Terms"})
    fake_pb.seed(
        "glossary_terms",
        {
            "glossary": glossary_id,
            "source_language": "en",
            "target_language": "fa",
            "source_term": "framework",
            "target_term": "چارچوب",
            "preferred": True,
        },
    )
    fake_pb.seed(
        "glossary_terms",
        {
            "glossary": glossary_id,
            "source_language": "en",
            "target_language": "de",
            "source_term": "framework",
            "target_term": "Framework",
            "exact_match": True,
        },
    )


async def test_retrieves_relevant_terms_only(pb, fake_pb) -> None:
    _seed(fake_pb)
    retriever = GlossaryRetriever(GlossaryTermRepository(pb), ["g1"])
    matches = await retriever.relevant("en", "fa", "A web framework for building apps")
    assert [m.target_term for m in matches] == ["چارچوب"]

    none = await retriever.relevant("en", "fa", "No relevant term here")
    assert none == []


async def test_exact_match_uses_word_boundaries(pb, fake_pb) -> None:
    _seed(fake_pb)
    retriever = GlossaryRetriever(GlossaryTermRepository(pb), ["g1"])
    assert await retriever.relevant("en", "de", "framework") != []
    assert await retriever.relevant("en", "de", "frameworks") == []


def test_glossary_lines_and_terminology() -> None:
    from app.translation.glossary import GlossaryMatch

    matches = [GlossaryMatch("framework", "چارچوب", preferred=True)]
    assert glossary_lines(matches) == ["framework => چارچوب (preferred)"]
    assert terminology_issues(matches, "no term") == ["Preferred term missing: 'چارچوب'."]
    assert terminology_issues(matches, "چارچوب") == []

    forbidden = [GlossaryMatch("bad", "غلط", forbidden=True)]
    assert terminology_issues(forbidden, "غلط") == ["Forbidden term used: 'غلط'."]
