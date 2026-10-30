"""PocketBase REST client.

All raw PocketBase HTTP calls live here; the rest of the application depends on
this typed client (or the higher-level auth service) rather than scattering
``httpx`` calls around the codebase.

The client knows nothing about HTML, sessions, or translation.
"""

from __future__ import annotations

from typing import Any

import httpx
import tenacity

from app.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    UpstreamError,
    ValidationError,
)
from app.logging import get_logger
from app.schemas.pocketbase import (
    PocketBaseAuthResponse,
    PocketBaseErrorBody,
    PocketBaseListResponse,
    PocketBaseRecord,
)

logger = get_logger(__name__)

# Transport-level retry for the metadata service. This is infrastructure
# resilience, distinct from (and unrelated to) translation retry policy, which
# is translation behaviour and therefore configuration-driven.
_RETRY_ATTEMPTS = 5


class PocketBaseClient:
    """Typed async client for the PocketBase REST API."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=15.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- low level -----------------------------------------------------------
    @tenacity.retry(
        stop=tenacity.stop_after_attempt(_RETRY_ATTEMPTS),
        wait=tenacity.wait_exponential(multiplier=0.5, max=4.0),
        retry=tenacity.retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = token
        try:
            response = await self._client.request(
                method, path, headers=headers, json=json, params=params
            )
        except httpx.TransportError as exc:
            logger.warning("pocketbase_transport_error", path=path, error=type(exc).__name__)
            raise UpstreamError(
                f"Could not reach the identity service ({type(exc).__name__} on {path})."
            ) from exc
        if response.status_code >= 400:
            raise self._map_error(response)
        return response

    @staticmethod
    def _map_error(response: httpx.Response) -> Exception:
        try:
            body = PocketBaseErrorBody.model_validate(response.json())
            message = body.message or "PocketBase request failed."
        except Exception:
            message = "PocketBase request failed."

        status = response.status_code
        if status == 400:
            return ValidationError(message)
        if status == 401:
            return AuthenticationError(message)
        if status == 403:
            return PermissionDeniedError(message)
        if status == 404:
            return NotFoundError(message)
        if status == 409:
            return ConflictError(message)
        if status == 429:
            return RateLimitedError(message)
        return UpstreamError(message)

    # -- health --------------------------------------------------------------
    async def health(self) -> bool:
        """Return True when PocketBase reports itself healthy."""
        try:
            response = await self._client.get("/api/health")
        except httpx.TransportError:
            return False
        return response.status_code == 200

    # -- auth ----------------------------------------------------------------
    async def authenticate_superuser(self, *, identity: str, password: str) -> str:
        """Exchange superuser credentials for a service token."""
        response = await self._request(
            "POST",
            "/api/collections/_superusers/auth-with-password",
            json={"identity": identity, "password": password},
        )
        return str(response.json()["token"])

    async def auth_methods(self, collection: str) -> dict[str, Any]:
        """Enabled auth methods and their per-request OAuth2 state."""
        response = await self._request("GET", f"/api/collections/{collection}/auth-methods")
        data: dict[str, Any] = response.json()
        return data

    async def auth_with_oauth2(
        self,
        collection: str,
        *,
        provider: str,
        code: str,
        code_verifier: str,
        redirect_url: str,
    ) -> PocketBaseAuthResponse:
        response = await self._request(
            "POST",
            f"/api/collections/{collection}/auth-with-oauth2",
            json={
                "provider": provider,
                "code": code,
                "codeVerifier": code_verifier,
                "redirectURL": redirect_url,
                "createData": {"emailVisibility": False},
            },
        )
        return PocketBaseAuthResponse.model_validate(response.json())

    async def auth_refresh(self, collection: str, *, token: str) -> PocketBaseAuthResponse:
        response = await self._request(
            "POST", f"/api/collections/{collection}/auth-refresh", token=token
        )
        return PocketBaseAuthResponse.model_validate(response.json())

    async def create_record(
        self, collection: str, data: dict[str, Any], *, token: str | None = None
    ) -> PocketBaseRecord:
        response = await self._request(
            "POST", f"/api/collections/{collection}/records", token=token, json=data
        )
        return PocketBaseRecord.model_validate(response.json())

    async def get_record(
        self, collection: str, record_id: str, *, token: str | None = None
    ) -> PocketBaseRecord:
        response = await self._request(
            "GET", f"/api/collections/{collection}/records/{record_id}", token=token
        )
        return PocketBaseRecord.model_validate(response.json())

    async def update_record(
        self,
        collection: str,
        record_id: str,
        data: dict[str, Any],
        *,
        token: str | None = None,
    ) -> PocketBaseRecord:
        response = await self._request(
            "PATCH",
            f"/api/collections/{collection}/records/{record_id}",
            token=token,
            json=data,
        )
        return PocketBaseRecord.model_validate(response.json())

    async def delete_record(
        self, collection: str, record_id: str, *, token: str | None = None
    ) -> None:
        await self._request(
            "DELETE", f"/api/collections/{collection}/records/{record_id}", token=token
        )

    async def list_records(
        self,
        collection: str,
        *,
        token: str | None = None,
        filter: str | None = None,
        page: int = 1,
        per_page: int = 30,
        sort: str | None = None,
    ) -> PocketBaseListResponse:
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if filter:
            params["filter"] = filter
        if sort:
            params["sort"] = sort
        response = await self._request(
            "GET", f"/api/collections/{collection}/records", token=token, params=params
        )
        return PocketBaseListResponse.model_validate(response.json())
