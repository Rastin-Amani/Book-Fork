"""Generic OpenAI-compatible chat-completions provider.

Works against any endpoint implementing the OpenAI chat-completions API
(OpenAI, Azure-style gateways, Ollama, vLLM, self-hosted gateways). No vendor is
hardcoded: base URL, model, authentication and limits come from configuration.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.observability.events import PROVIDER_ERROR, emit
from app.observability.metrics import metrics
from app.providers.base import (
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from app.providers.errors import (
    ProviderError,
    ProviderErrorCategory,
    classify_error_response,
)

_CHARS_PER_TOKEN = 4
_SNIPPET_CHARS = 500


def _snippet(text: str) -> str:
    """Truncated upstream response text for diagnostics (never a credential)."""
    text = (text or "").strip()
    return text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + "…"


def _extract_completion(
    response: httpx.Response,
) -> tuple[str, dict[str, Any], str | None, str | None]:
    """Read a completion from either a JSON body or an SSE stream.

    Some OpenAI-compatible gateways answer with ``text/event-stream`` chunks even
    when streaming was not requested, so both shapes must be handled.
    """
    text = response.text
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type or text.lstrip().startswith("data:"):
        return _parse_sse(text)
    body = response.json()
    choice = body["choices"][0]["message"]["content"]
    usage: dict[str, Any] = body.get("usage") or {}
    finish_reason = body["choices"][0].get("finish_reason")
    response_id = body.get("id")
    return choice, usage, finish_reason, response_id


def _parse_sse(text: str) -> tuple[str, dict[str, Any], str | None, str | None]:
    """Concatenate assistant content from SSE ``chat.completion.chunk`` events."""
    parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    response_id: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        if isinstance(chunk.get("id"), str):
            response_id = chunk["id"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            piece = delta.get("content")
            if isinstance(piece, str):
                parts.append(piece)
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    return "".join(parts), usage, finish_reason, response_id


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None = None,
        api_key: str | None = None,
        auth_scheme: str = "Bearer",
        auth_header: str = "Authorization",
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 10 * 1024 * 1024,
        supports_structured_output: bool = True,
        extra_headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._auth_header = auth_header
        self._auth_scheme = auth_scheme
        self._api_key = api_key
        self._max_response_bytes = max_response_bytes
        self.supports_structured_output = supports_structured_output
        self._extra_headers = dict(extra_headers or {})
        headers = dict(self._extra_headers)
        if api_key:
            headers[auth_header] = f"{auth_scheme} {api_key}".strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers=headers,
            follow_redirects=False,  # untrusted endpoints must not be followed
        )
        self._base_url = base_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def diagnose(self) -> str:
        """Safe connection diagnostic: connected | authentication_failed | endpoint_unreachable."""
        try:
            response = await self._client.get("/models")
        except httpx.HTTPError:
            return "endpoint_unreachable"
        if response.status_code in (401, 403):
            return "authentication_failed"
        if response.status_code < 400:
            return "connected"
        if response.status_code >= 500:
            return "endpoint_unreachable"
        return "model_unavailable"

    async def validate_connection(self) -> bool:
        return await self.diagnose() == "connected"

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        payload = self._build_payload(request)
        started = time.perf_counter()
        try:
            response = await self._client.post(
                "/chat/completions", json=payload, timeout=request.timeout_seconds
            )
        except httpx.TimeoutException as exc:
            self._record_error(ProviderErrorCategory.TIMEOUT)
            raise ProviderError(ProviderErrorCategory.TIMEOUT) from exc
        except httpx.TransportError as exc:
            self._record_error(ProviderErrorCategory.UNAVAILABLE)
            raise ProviderError(ProviderErrorCategory.UNAVAILABLE) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        if response.status_code >= 400:
            category = classify_error_response(response.status_code, response.text)
            self._record_error(category)
            raise ProviderError(
                category,
                f"Provider returned HTTP {response.status_code}: {_snippet(response.text)}",
            )
        if len(response.content) > self._max_response_bytes:
            self._record_error(ProviderErrorCategory.INVALID_RESPONSE)
            raise ProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "Provider response exceeded the size limit."
            )

        try:
            choice, raw_usage, finish_reason, response_id = _extract_completion(response)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._record_error(ProviderErrorCategory.INVALID_RESPONSE)
            raise ProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                f"Unparseable provider response: {_snippet(response.text)}",
            ) from exc

        if not isinstance(choice, str):
            self._record_error(ProviderErrorCategory.INVALID_RESPONSE)
            raise ProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                f"Provider returned non-text content: {_snippet(response.text)}",
            )

        usage = ProviderUsage(
            input_tokens=int(raw_usage.get("prompt_tokens") or 0),
            output_tokens=int(raw_usage.get("completion_tokens") or 0),
            estimated=False,
            latency_ms=latency_ms,
        )
        metrics.inc("book_fork_provider_requests_total", provider=self.name)
        metrics.inc("book_fork_provider_latency_ms_total", latency_ms)
        return ProviderResponse(
            translations={},
            content=choice,
            usage=usage,
            raw_metadata={"finish_reason": finish_reason, "id": response_id},
            structured=bool(request.structured and self.supports_structured_output),
        )

    def _record_error(self, category: ProviderErrorCategory) -> None:
        metrics.inc("book_fork_provider_errors_total", category=category.value, provider=self.name)
        emit(PROVIDER_ERROR, category=category.value, provider=self.name)

    async def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        input_chars = len(request.user_prompt) + len(request.system_prompt or "")
        output_chars = sum(len(segment.text) for segment in request.segments)
        return ProviderUsage(
            input_tokens=input_chars // _CHARS_PER_TOKEN,
            output_tokens=output_chars // _CHARS_PER_TOKEN,
            estimated=True,
        )

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})

        payload: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": messages,
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if (
            request.structured
            and self.supports_structured_output
            and request.response_schema is not None
        ):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "translation_batch",
                    "schema": request.response_schema,
                    "strict": True,
                },
            }
        return payload
