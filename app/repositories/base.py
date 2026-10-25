"""Generic typed PocketBase repository.

Business services depend on these repositories instead of calling the
PocketBase client directly. Field names of the domain model mirror the
collection fields, so mapping is a direct validation.
"""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Mapping
from functools import cache
from typing import Any, ClassVar, get_args, get_origin

from pydantic import BaseModel

from app.repositories.pocketbase import PocketBaseClient
from app.schemas.pocketbase import PocketBaseRecord

# Upper bound on concurrent PocketBase page fetches for ``list_all``. Keeps a
# huge collection from opening a socket per page while still collapsing the
# serial round-trip-per-page cost.
_LIST_ALL_CONCURRENCY = 5


def escape_filter_value(value: str) -> str:
    """Escape a value for safe interpolation into a PocketBase filter string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def filter_eq(field: str, value: str) -> str:
    """Build an equality filter clause with an escaped value."""
    return f'{field} = "{escape_filter_value(value)}"'


def _accepts_text(annotation: Any) -> bool:
    """Whether a field annotation can hold a plain string (incl. ``StrEnum``)."""
    if isinstance(annotation, type):
        return issubclass(annotation, str)
    origin = get_origin(annotation)
    if origin is not None:
        return any(_accepts_text(arg) for arg in get_args(annotation))
    return False


@cache
def _empty_string_is_absent(model: type[BaseModel]) -> frozenset[str]:
    """Fields where PocketBase's ``''`` means "unset" rather than a value.

    PocketBase serializes unset fields as ``''`` (not ``null``). For optional
    fields ``''`` means "no value" (an unset relation, date or text); for
    non-text fields ``''`` was never valid. Required text fields are the only
    place ``''`` can legitimately be a value, so those are left untouched.
    """
    return frozenset(
        name
        for name, field in model.model_fields.items()
        if not field.is_required() or not _accepts_text(field.annotation)
    )


class PocketBaseRepository[M: BaseModel]:
    """CRUD + list over a single PocketBase collection."""

    collection: ClassVar[str]
    model: ClassVar[type[BaseModel]]

    def __init__(self, client: PocketBaseClient, *, token: str | None = None) -> None:
        self._client = client
        self._token = token

    def with_token(self, token: str | None) -> PocketBaseRepository[M]:
        """Return a view of this repository bound to a request token."""
        return type(self)(self._client, token=token)

    def _to_model(self, record: PocketBaseRecord) -> M:
        # PocketBase returns null for unset JSON fields and '' for unset text,
        # relation, date and number fields. Drop both so the model's declared
        # defaults apply (e.g. datetime | None vs '', relation id vs None).
        absent = _empty_string_is_absent(self.model)
        data = {
            key: value
            for key, value in record.model_dump().items()
            if value is not None and not (value == "" and key in absent)
        }
        return self.model.model_validate(data)  # type: ignore[return-value]

    async def get(self, record_id: str, *, token: str | None = None) -> M:
        record = await self._client.get_record(
            self.collection, record_id, token=token or self._token
        )
        return self._to_model(record)

    async def list(
        self,
        *,
        filter: str | None = None,
        page: int = 1,
        per_page: int = 100,
        sort: str | None = None,
        token: str | None = None,
    ) -> list[M]:
        result = await self._client.list_records(
            self.collection,
            token=token or self._token,
            filter=filter,
            page=page,
            per_page=per_page,
            sort=sort,
        )
        return [self._to_model(item) for item in result.items]

    async def list_all(
        self,
        *,
        filter: str | None = None,
        sort: str | None = None,
        token: str | None = None,
        per_page: int = 500,
    ) -> builtins.list[M]:
        """Return every matching record, paging past PocketBase's per-request cap.

        ``list`` silently returns only the first page (100 by default); any
        caller that must see *all* rows (segments of a large book, attempts,
        events) has to page explicitly.

        Page 1 reveals ``totalPages``; the remainder are fetched concurrently
        (bounded) so a 1500-segment book costs two round trips instead of
        three. Bounded so a huge collection cannot open unbounded sockets.
        """
        effective_token = token or self._token
        first = await self._client.list_records(
            self.collection,
            token=effective_token,
            filter=filter,
            page=1,
            per_page=per_page,
            sort=sort,
        )
        results: builtins.list[M] = [self._to_model(item) for item in first.items]
        extra_pages = range(2, first.totalPages + 1) if first.items else ()
        if not extra_pages:
            return results

        semaphore = asyncio.Semaphore(_LIST_ALL_CONCURRENCY)

        async def _fetch_page(page: int) -> tuple[int, list[M]]:
            async with semaphore:
                result = await self._client.list_records(
                    self.collection,
                    token=effective_token,
                    filter=filter,
                    page=page,
                    per_page=per_page,
                    sort=sort,
                )
            return page, [self._to_model(item) for item in result.items]

        batches = await asyncio.gather(*(_fetch_page(page) for page in extra_pages))
        for _, items in sorted(batches):
            results.extend(items)
        return results

    async def first(
        self,
        *,
        filter: str | None = None,
        sort: str | None = None,
        token: str | None = None,
    ) -> M | None:
        items = await self.list(filter=filter, per_page=1, sort=sort, token=token)
        return items[0] if items else None

    async def count(self, *, filter: str | None = None, token: str | None = None) -> int:
        """Return the total number of matching records (server-side count)."""
        result = await self._client.list_records(
            self.collection,
            token=token or self._token,
            filter=filter,
            page=1,
            per_page=1,
        )
        return result.totalItems

    async def create(self, data: Mapping[str, Any] | BaseModel, *, token: str | None = None) -> M:
        payload = _payload(data)
        record = await self._client.create_record(
            self.collection, payload, token=token or self._token
        )
        return self._to_model(record)

    async def update(
        self,
        record_id: str,
        data: Mapping[str, Any] | BaseModel,
        *,
        token: str | None = None,
    ) -> M:
        payload = _payload(data)
        record = await self._client.update_record(
            self.collection, record_id, payload, token=token or self._token
        )
        return self._to_model(record)

    async def delete(self, record_id: str, *, token: str | None = None) -> None:
        await self._client.delete_record(self.collection, record_id, token=token or self._token)


def _payload(data: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        return data.model_dump(exclude_none=True, mode="json")
    return dict(data)
