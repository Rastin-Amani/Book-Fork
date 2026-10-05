"""Workspace bootstrap service."""

from __future__ import annotations

from app.repositories.workspaces import WorkspaceMemberRepository, WorkspaceRepository
from app.workspaces.service import WorkspaceService


def _service(pb) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(pb), WorkspaceMemberRepository(pb))


async def test_creates_personal_workspace_once(pb, fake_pb) -> None:
    service = _service(pb)
    first = await service.get_or_create_personal("u1")
    second = await service.get_or_create_personal("u1")
    assert first.id == second.id
    members = await WorkspaceMemberRepository(pb).list_for_workspace(first.id)
    assert len(members) == 1
    assert members[0].user == "u1"
    assert members[0].role.value == "owner"


async def test_separate_users_get_separate_workspaces(pb, fake_pb) -> None:
    service = _service(pb)
    a = await service.get_or_create_personal("u1")
    b = await service.get_or_create_personal("u2")
    assert a.id != b.id
