from typing import Protocol

from app.domain.users.entities import User, Workspace, WorkspaceMember


class UserRepositoryPort(Protocol):
    def get_by_id(self, user_id: str) -> User | None:
        ...

    def get_by_email(self, email: str) -> User | None:
        ...


class WorkspaceRepositoryPort(Protocol):
    def get(self, workspace_id: str) -> Workspace | None:
        ...

    def list_for_user(self, user_id: str) -> list[Workspace]:
        ...

    def membership(self, user_id: str, workspace_id: str) -> WorkspaceMember | None:
        ...


class WorkspaceAccessPort(Protocol):
    def ensure_workspace_member(self, user_id: str, workspace_id: str) -> None:
        ...
