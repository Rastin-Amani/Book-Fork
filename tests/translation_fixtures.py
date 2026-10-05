"""Fake provider and plan builders for translation-engine tests (no network)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any

from app.providers.base import ProviderRequest, ProviderResponse, ProviderUsage
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.translation.plan import (
    LanguageSpec,
    RetryPolicy,
    TranslationPlan,
)

Transform = Callable[[str], str]


def make_plan(
    *,
    source: str = "en",
    target: str = "fa",
    batch_size: int = 20,
    prompt_body: str | None = None,
    normalization: dict[str, Any] | None = None,
    retry: RetryPolicy | None = None,
    target_direction: str = "rtl",
    target_script: str = "Arab",
    profile_snapshot: dict[str, Any] | None = None,
    validation_profile: dict[str, Any] | None = None,
) -> TranslationPlan:
    return TranslationPlan(
        source=LanguageSpec(tag=source, locale=source, script="Latn", direction="ltr", name=source),
        target=LanguageSpec(
            tag=target, locale=target, script=target_script, direction=target_direction, name=target
        ),
        prompt_body=prompt_body
        or "Translate from {{ source_language }} to {{ target_language }}.\n{{ source_segments }}",
        batch_size=batch_size,
        normalization_pipeline=normalization or {},
        validation_profile=validation_profile or {},
        retry_policy=retry
        or RetryPolicy(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0),
        profile_snapshot=profile_snapshot or {},
    )


def no_sleep() -> Callable[[float], Any]:
    async def _sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    return _sleep


class FakeProvider:
    name = "fake"
    supports_structured_output = True

    def __init__(
        self,
        *,
        transform: Transform | None = None,
        errors: Sequence[ProviderError] | None = None,
        fail_first: int = 0,
        response_builder: Callable[[ProviderRequest], ProviderResponse] | None = None,
    ) -> None:
        self.calls = 0
        self.requests: list[ProviderRequest] = []
        self._errors = list(errors or [])
        self._fail_first = fail_first
        self._transform: Transform = transform or (lambda text: "TR::" + text)
        self._response_builder = response_builder

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        self.requests.append(request)
        if self._fail_first > 0:
            self._fail_first -= 1
            raise ProviderError(ProviderErrorCategory.RATE_LIMITED)
        if self._errors:
            raise self._errors.pop(0)
        if self._response_builder is not None:
            return self._response_builder(request)
        items = [
            {"segment_id": segment.id, "translation": self._transform(segment.text)}
            for segment in request.segments
        ]
        return ProviderResponse(
            content=json.dumps({"translations": items}),
            usage=ProviderUsage(input_tokens=10, output_tokens=20),
            structured=request.structured,
        )

    async def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        return ProviderUsage(
            input_tokens=len(request.user_prompt) // 4, output_tokens=1, estimated=True
        )

    async def validate_connection(self) -> bool:
        return True


def content_for(items: list[dict[str, str]]) -> str:
    return json.dumps({"translations": items})
