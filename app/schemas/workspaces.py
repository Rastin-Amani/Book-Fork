"""Workspace domain records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Workspace(Record):
    name: str
    slug: str
    owner: str
    plan: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMember(Record):
    workspace: str
    user: str
    role: WorkspaceRole
