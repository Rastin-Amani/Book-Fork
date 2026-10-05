"""Transport schemas for PocketBase REST responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PocketBaseRecord(BaseModel):
    """Generic PocketBase record; extra collection fields are preserved."""

    model_config = ConfigDict(extra="allow")

    id: str
    collectionId: str | None = None
    collectionName: str | None = None
    created: str | None = None
    updated: str | None = None
    email: str | None = None
    verified: bool | None = None
    name: str | None = None


class PocketBaseAuthResponse(BaseModel):
    token: str
    record: PocketBaseRecord


class PocketBaseListResponse(BaseModel):
    page: int = 1
    perPage: int = 30
    totalItems: int = 0
    totalPages: int = 0
    items: list[PocketBaseRecord] = Field(default_factory=list)


class PocketBaseErrorBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: int = 400
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
