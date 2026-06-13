from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.workspaces.service import WorkspaceService
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import get_db
from app.interfaces.api.dependencies import get_current_user, storage_dependency

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    voice_style_preference: str | None = None


@router.post("")
def create_workspace(
    payload: WorkspaceCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return WorkspaceService(db).create(user.id, payload.name)


@router.get("")
def list_workspaces(db: Session = Depends(get_db), user: UserModel = Depends(get_current_user)) -> list[dict]:
    return WorkspaceService(db).list_for_user(user.id)


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return WorkspaceService(db).get(user.id, workspace_id)


@router.patch("/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return WorkspaceService(db).update(
        user.id,
        workspace_id,
        name=payload.name,
        voice_style_preference=payload.voice_style_preference,
    )


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    storage=Depends(storage_dependency),
) -> dict:
    return WorkspaceService(db, storage=storage).delete(user.id, workspace_id)
