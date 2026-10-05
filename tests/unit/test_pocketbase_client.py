"""Unit tests for the PocketBase client error mapping (mocked transport)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest
from app.exceptions import (
    AuthenticationError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from app.repositories.pocketbase import PocketBaseClient

Handler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]


def _client(handler: Handler) -> tuple[PocketBaseClient, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://pb")
    return PocketBaseClient("http://pb", client=http), http


async def test_auth_success_parses_session() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"token": "tok", "record": {"id": "u1", "email": "a@b.co", "verified": True}},
        )

    pb, http = _client(handler)
    try:
        result = await pb.auth_with_password("users", identity="a@b.co", password="x")
        assert result.token == "tok"
        assert result.record.id == "u1"
    finally:
        await http.aclose()


async def test_auth_401_maps_to_authentication_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": 401, "message": "invalid"})

    pb, http = _client(handler)
    try:
        with pytest.raises(AuthenticationError):
            await pb.auth_with_password("users", identity="a", password="b")
    finally:
        await http.aclose()


async def test_400_maps_to_validation_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"status": 400, "message": "bad email"})

    pb, http = _client(handler)
    try:
        with pytest.raises(ValidationError):
            await pb.create_record("users", {"email": "bad"})
    finally:
        await http.aclose()


async def test_404_maps_to_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": 404, "message": "missing"})

    pb, http = _client(handler)
    try:
        with pytest.raises(NotFoundError):
            await pb.get_record("users", "missing")
    finally:
        await http.aclose()


async def test_500_maps_to_upstream_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": 500, "message": "boom"})

    pb, http = _client(handler)
    try:
        with pytest.raises(UpstreamError):
            await pb.get_record("users", "u1")
    finally:
        await http.aclose()
