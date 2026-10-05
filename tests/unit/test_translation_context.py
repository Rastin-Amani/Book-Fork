"""Context policies and bounding."""

from __future__ import annotations

from app.translation.context import ContextInputs, TranslationContextBuilder
from app.translation.plan import ContextPolicy


def _inputs() -> ContextInputs:
    return ContextInputs(
        document_metadata={"title": "Book", "authors": ["Ada"]},
        section_title="Chapter 1",
        previous_segments=["p1", "p2", "p3", "p4"],
        next_segments=["n1", "n2"],
        glossary_lines=["framework => چارچوب"],
        memory_lines=["Hello => سلام"],
    )


def test_minimal_excludes_neighbour_context() -> None:
    built = TranslationContextBuilder().build(ContextPolicy(strategy="minimal"), _inputs())
    assert built.previous_context == ""
    assert built.next_context == ""
    assert built.document_context == "Book"


def test_previous_segments_strategy() -> None:
    built = TranslationContextBuilder().build(
        ContextPolicy(strategy="previous_segments", max_previous_segments=2), _inputs()
    )
    assert built.previous_context == "p3\np4"
    assert built.next_context == ""


def test_adaptive_includes_next_bounded() -> None:
    built = TranslationContextBuilder().build(
        ContextPolicy(strategy="adaptive", max_previous_segments=1), _inputs()
    )
    assert built.previous_context == "p4"
    assert built.next_context == "n1"


def test_token_limit_drops_context() -> None:
    built = TranslationContextBuilder().build(
        ContextPolicy(strategy="adaptive", max_context_tokens=1), _inputs()
    )
    assert built.next_context == "" and built.previous_context == ""


def test_prompt_variables_are_allowlisted() -> None:
    built = TranslationContextBuilder().build(ContextPolicy(), _inputs())
    variables = built.as_prompt_variables()
    assert set(variables) == {
        "document_context",
        "chapter_context",
        "previous_context",
        "next_context",
        "glossary",
        "translation_memory",
    }
    assert variables["glossary"] == "framework => چارچوب"
