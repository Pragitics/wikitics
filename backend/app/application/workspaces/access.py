from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.infrastructure.db.models import WorkspaceMemberModel


def ensure_workspace_member(db: Session, user_id: str, workspace_id: str) -> None:
    membership = (
        db.query(WorkspaceMemberModel)
        .filter(WorkspaceMemberModel.user_id == user_id, WorkspaceMemberModel.workspace_id == workspace_id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
