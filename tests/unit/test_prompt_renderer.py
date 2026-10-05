"""Safe prompt template rendering."""

from __future__ import annotations

import pytest
from app.exceptions import PromptRenderError
from app.prompts.renderer import PromptRenderer


def test_renders_allowed_variables() -> None:
    renderer = PromptRenderer()
    body = "Translate {{ source_language }} to {{ target_language }}:\n{{ source_segments }}"
    result = renderer.render(
        body,
        {
            "source_language": "English",
            "target_language": "Persian",
            "source_segments": "[[s1]] Hello",
        },
    )
    assert "English" in result
    assert "Persian" in result
    assert "[[s1]] Hello" in result


def test_unknown_variable_rejected() -> None:
    renderer = PromptRenderer()
    with pytest.raises(PromptRenderError):
        renderer.render("{{ os }}", {"os": "linux"})


def test_missing_variable_raises() -> None:
    renderer = PromptRenderer()
    with pytest.raises(PromptRenderError):
        renderer.render("{{ source_segments }}", {})


def test_empty_body_rejected() -> None:
    renderer = PromptRenderer()
    with pytest.raises(PromptRenderError):
        renderer.render("   ", {"source_language": "en"})


def test_sandbox_blocks_dangerous_attribute_access() -> None:
    renderer = PromptRenderer()
    with pytest.raises(PromptRenderError):
        renderer.render("{{ source_segments.__class__.__mro__ }}", {"source_segments": "x"})


def test_no_code_execution() -> None:
    renderer = PromptRenderer()
    with pytest.raises(PromptRenderError):
        renderer.render("{{ source_language }}{{ ''.__class__ }}", {"source_language": "en"})
