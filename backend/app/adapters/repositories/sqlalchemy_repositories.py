from sqlalchemy.orm import Session

from app.domain.users.entities import User, Workspace, WorkspaceMember, WorkspaceRole
from app.infrastructure.db.models import UserModel, WorkspaceMemberModel, WorkspaceModel


class SQLAlchemyUserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: str) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return _user_entity(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.email == email.lower()).first()
        return _user_entity(row) if row else None


class SQLAlchemyWorkspaceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, workspace_id: str) -> Workspace | None:
        row = self.db.query(WorkspaceModel).filter(WorkspaceModel.id == workspace_id).first()
        return _workspace_entity(row) if row else None

    def list_for_user(self, user_id: str) -> list[Workspace]:
        rows = (
            self.db.query(WorkspaceModel)
            .join(WorkspaceMemberModel, WorkspaceMemberModel.workspace_id == WorkspaceModel.id)
            .filter(WorkspaceMemberModel.user_id == user_id)
            .order_by(WorkspaceModel.created_at.desc())
            .all()
        )
        return [_workspace_entity(row) for row in rows]

    def membership(self, user_id: str, workspace_id: str) -> WorkspaceMember | None:
        row = (
            self.db.query(WorkspaceMemberModel)
            .filter(WorkspaceMemberModel.user_id == user_id, WorkspaceMemberModel.workspace_id == workspace_id)
            .first()
        )
        return _member_entity(row) if row else None


def _user_entity(row: UserModel) -> User:
    return User(id=row.id, email=row.email, name=row.name)


def _workspace_entity(row: WorkspaceModel) -> Workspace:
    return Workspace(id=row.id, name=row.name, owner_id=row.owner_id)


def _member_entity(row: WorkspaceMemberModel) -> WorkspaceMember:
    return WorkspaceMember(
        id=row.id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        role=WorkspaceRole(row.role),
    )
