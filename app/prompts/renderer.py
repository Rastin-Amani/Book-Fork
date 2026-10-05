"""Safe prompt template rendering.

Templates are database entities rendered with a Jinja2 sandbox and a strict
allow-list of variables. No ``eval``, no arbitrary attribute access, no
unrestricted environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.exceptions import PromptRenderError

# The complete set of variables a prompt may reference. Anything else is
# rejected, so a template cannot reach into application state.
ALLOWED_VARIABLES: frozenset[str] = frozenset(
    {
        "source_language",
        "source_locale",
        "target_language",
        "target_locale",
        "style",
        "tone",
        "domain",
        "glossary",
        "translation_memory",
        "document_context",
        "chapter_context",
        "previous_context",
        "next_context",
        "source_segments",
    }
)


class PromptRenderer:
    """Renders versioned prompt bodies with a constrained variable set."""

    def __init__(self) -> None:
        self._env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)

    def render(self, body: str, variables: Mapping[str, Any]) -> str:
        unknown = set(variables) - ALLOWED_VARIABLES
        if unknown:
            raise PromptRenderError(f"Unknown prompt variables: {', '.join(sorted(unknown))}.")
        if not isinstance(body, str) or not body.strip():
            raise PromptRenderError("Prompt body is empty.")
        try:
            template = self._env.from_string(body)
            return template.render(**variables)
        except TemplateError as exc:
            raise PromptRenderError("The prompt template could not be rendered.") from exc
