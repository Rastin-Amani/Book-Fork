"""Workspace ownership and authorization.

The backend verifies ownership on every resource operation. PocketBase rules
provide defense in depth; this service is the application-level check.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.exceptions import PermissionDeniedError
from app.repositories.workspaces import WorkspaceMemberRepository, WorkspaceRepository
from app.schemas.workspaces import WorkspaceRole


@dataclass(frozen=True, slots=True)
class AccessGrant:
    workspace_id: str
    user_id: str
    role: WorkspaceRole


class WorkspaceAccess:
    """Resolves and enforces a user's access to a workspace."""

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

    async def grant(self, user_id: str, workspace_id: str) -> AccessGrant | None:
        membership = await self._members.get_membership(workspace_id, user_id, token=self._token)
        if membership is not None:
            return AccessGrant(workspace_id, user_id, membership.role)
        workspace = await self._workspaces.get(workspace_id, token=self._token)
        if workspace is not None and workspace.owner == user_id:
            return AccessGrant(workspace_id, user_id, WorkspaceRole.OWNER)
        return None

    async def ensure_member(self, user_id: str, workspace_id: str) -> AccessGrant:
        grant = await self.grant(user_id, workspace_id)
        if grant is None:
            raise PermissionDeniedError("You do not have access to this workspace.")
        return grant

    async def ensure_role(
        self,
        user_id: str,
        workspace_id: str,
        roles: Collection[WorkspaceRole],
    ) -> AccessGrant:
        grant = await self.ensure_member(user_id, workspace_id)
        if grant.role not in roles:
            raise PermissionDeniedError("Your workspace role does not allow this action.")
        return grant
