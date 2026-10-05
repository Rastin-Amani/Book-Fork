"""Workspace ownership and authorization."""

from __future__ import annotations

import pytest
from app.exceptions import PermissionDeniedError
from app.repositories.workspaces import WorkspaceMemberRepository, WorkspaceRepository
from app.schemas.workspaces import WorkspaceRole
from app.workspaces.authz import WorkspaceAccess


def _access(pb) -> WorkspaceAccess:
    return WorkspaceAccess(WorkspaceRepository(pb), WorkspaceMemberRepository(pb))


async def test_member_access(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "owner-1"})
    fake_pb.seed("workspace_members", {"workspace": ws["id"], "user": "member-1", "role": "member"})
    grant = await _access(pb).ensure_member("member-1", ws["id"])
    assert grant.role is WorkspaceRole.MEMBER


async def test_owner_access_without_membership_row(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "owner-1"})
    grant = await _access(pb).ensure_member("owner-1", ws["id"])
    assert grant.role is WorkspaceRole.OWNER


async def test_non_member_denied(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "owner-1"})
    with pytest.raises(PermissionDeniedError):
        await _access(pb).ensure_member("stranger", ws["id"])


async def test_role_enforcement(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "owner-1"})
    fake_pb.seed("workspace_members", {"workspace": ws["id"], "user": "member-1", "role": "member"})
    access = _access(pb)
    grant = await access.ensure_role("member-1", ws["id"], {WorkspaceRole.MEMBER})
    assert grant.user_id == "member-1"
    with pytest.raises(PermissionDeniedError):
        await access.ensure_role("member-1", ws["id"], {WorkspaceRole.ADMIN})
