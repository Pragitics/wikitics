from dataclasses import dataclass
from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    owner_id: str


@dataclass(frozen=True)
class WorkspaceMember:
    id: str
    workspace_id: str
    user_id: str
    role: WorkspaceRole
