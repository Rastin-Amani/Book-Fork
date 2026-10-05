"""Workspace bootstrap service.

Every user gets a personal workspace on first use. The workspace is the
ownership boundary for documents, jobs, providers, glossaries, wallets and
memory.
"""

from __future__ import annotations

from app.repositories.base import filter_eq
from app.repositories.workspaces import WorkspaceMemberRepository, WorkspaceRepository
from app.schemas.workspaces import Workspace, WorkspaceRole


class WorkspaceService:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        members: WorkspaceMemberRepository,
        *,
        token: str | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._members = members
        self._token = token

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        return await self._workspaces.list_for_user(user_id, token=self._token)

    async def get_or_create_personal(self, user_id: str, *, name: str | None = None) -> Workspace:
        existing = await self._workspaces.first(
            filter=filter_eq("owner", user_id), sort="created", token=self._token
        )
        if existing is not None:
            return existing
        workspace = await self._workspaces.create(
            {
                "name": name or "Personal workspace",
                "slug": f"personal-{user_id}",
                "owner": user_id,
                "plan": "free",
            },
            token=self._token,
        )
        await self._members.create(
            {"workspace": workspace.id, "user": user_id, "role": WorkspaceRole.OWNER.value},
            token=self._token,
        )
        return workspace
