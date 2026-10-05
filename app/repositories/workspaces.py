"""Workspace and membership repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.workspaces import Workspace, WorkspaceMember


class WorkspaceRepository(PocketBaseRepository[Workspace]):
    collection = "workspaces"
    model = Workspace

    async def get_by_slug(self, slug: str, *, token: str | None = None) -> Workspace | None:
        return await self.first(filter=filter_eq("slug", slug), token=token)

    async def list_for_user(self, user_id: str, *, token: str | None = None) -> list[Workspace]:
        clause = f'workspace_members_via_workspace.user = "{escape_filter_value(user_id)}"'
        return await self.list(filter=clause, token=token)


class WorkspaceMemberRepository(PocketBaseRepository[WorkspaceMember]):
    collection = "workspace_members"
    model = WorkspaceMember

    async def get_membership(
        self, workspace_id: str, user_id: str, *, token: str | None = None
    ) -> WorkspaceMember | None:
        clause = (
            f'workspace = "{escape_filter_value(workspace_id)}"'
            f' && user = "{escape_filter_value(user_id)}"'
        )
        return await self.first(filter=clause, token=token)

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[WorkspaceMember]:
        return await self.list(filter=filter_eq("workspace", workspace_id), token=token)
