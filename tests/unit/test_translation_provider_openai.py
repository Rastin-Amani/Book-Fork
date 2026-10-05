"""OpenAI-compatible provider against a mocked transport."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.providers.base import ProviderRequest, ProviderSegment
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.providers.openai_compatible import OpenAICompatibleProvider


def _provider(handler) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://pb")
    return OpenAICompatibleProvider(base_url="http://pb", model="m1", api_key="k", client=client)


def _request() -> ProviderRequest:
    return ProviderRequest(
        segments=[ProviderSegment(id="s1", text="Hello")],
        user_prompt="Translate:\n[[s1]] Hello",
        model=None,
        structured=True,
        response_schema={"type": "object"},
    )


async def test_translate_parses_content_and_usage() -> None:
    captured: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "req1",
                "choices": [
                    {
                        "message": {
                            "content": '{"translations":[{"segment_id":"s1","translation":"x"}]}'
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )

    response = await _provider(handler).translate(_request())
    assert "s1" in (response.content or "")
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 7
    assert response.usage.estimated is False
    payload = captured[0]
    assert payload["model"] == "m1"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True


async def test_translate_parses_sse_stream() -> None:
    # Gateways that ignore `stream: false` and answer with SSE chunks must work.
    captured: list[dict[str, Any]] = []
    body = (
        'data: {"id":"c1","choices":[{"index":0,"delta":{"role":"assistant","content":""},'
        '"finish_reason":null}]}\n\n'
        'data: {"id":"c1","choices":[{"index":0,"delta":{"content":"[[s1]] trans"},'
        '"finish_reason":null}]}\n\n'
        'data: {"id":"c1","choices":[{"index":0,"delta":{"content":"lated"},'
        '"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":4}}\n\n'
        "data: [DONE]\n\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    response = await _provider(handler).translate(_request())
    assert response.content == "[[s1]] translated"
    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens == 4
    assert captured[0]["stream"] is False


async def test_error_statuses_are_categorized() -> None:
    async def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "no"})

    async def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    with pytest.raises(ProviderError) as exc:
        await _provider(unauthorized).translate(_request())
    assert exc.value.category is ProviderErrorCategory.AUTHENTICATION
    assert exc.value.retryable is False

    with pytest.raises(ProviderError) as exc2:
        await _provider(limited).translate(_request())
    assert exc2.value.category is ProviderErrorCategory.RATE_LIMITED
    assert exc2.value.retryable is True


async def test_timeout_is_categorized() -> None:
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    with pytest.raises(ProviderError) as exc:
        await _provider(timeout).translate(_request())
    assert exc.value.category is ProviderErrorCategory.TIMEOUT


async def test_invalid_response_is_categorized() -> None:
    async def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ProviderError) as exc:
        await _provider(bad).translate(_request())
    assert exc.value.category is ProviderErrorCategory.INVALID_RESPONSE


async def test_estimate_usage_is_marked_estimated() -> None:
    provider = _provider(lambda request: httpx.Response(200, json={}))
    usage = await provider.estimate_usage(_request())
    assert usage.estimated is True
    assert usage.input_tokens >= 0


async def test_validate_connection() -> None:
    async def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async def no(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    assert await _provider(ok).validate_connection() is True
    assert await _provider(no).validate_connection() is False
