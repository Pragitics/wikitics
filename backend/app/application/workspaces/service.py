from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.workspaces.access import ensure_workspace_member
from app.infrastructure.db.models import (
    ChunkModel,
    CitationModel,
    ConversationModel,
    DocumentModel,
    DocumentVersionModel,
    ExtractedDocumentModel,
    MessageModel,
    VoiceSessionModel,
    WikiAbsorbLogModel,
    WikiLinkModel,
    WikiMaintenanceLogModel,
    WikiPageModel,
    WikiRevisionModel,
    WorkspaceMemberModel,
    WorkspaceModel,
)
from app.shared.ids import new_id


VOICE_STYLE_PREFERENCES = {"auto", "english", "hinglish", "tanglish", "regional_mix"}


class WorkspaceService:
    def __init__(self, db: Session, vector_search=None, storage=None) -> None:
        self.db = db
        self.vector_search = vector_search
        self.storage = storage

    def create(self, user_id: str, name: str) -> dict:
        workspace = WorkspaceModel(id=new_id(), name=name.strip(), owner_id=user_id)
        member = WorkspaceMemberModel(id=new_id(), workspace_id=workspace.id, user_id=user_id, role="owner")
        self.db.add_all([workspace, member])
        self.db.commit()
        return serialize_workspace(workspace)

    def list_for_user(self, user_id: str) -> list[dict]:
        rows = (
            self.db.query(WorkspaceModel)
            .join(WorkspaceMemberModel, WorkspaceMemberModel.workspace_id == WorkspaceModel.id)
            .filter(WorkspaceMemberModel.user_id == user_id)
            .order_by(WorkspaceModel.created_at.desc())
            .all()
        )
        return [serialize_workspace(row) for row in rows]

    def get(self, user_id: str, workspace_id: str) -> dict:
        ensure_workspace_member(self.db, user_id, workspace_id)
        workspace = self.db.query(WorkspaceModel).filter(WorkspaceModel.id == workspace_id).first()
        return serialize_workspace(workspace)

    def update(
        self,
        user_id: str,
        workspace_id: str,
        name: str | None = None,
        voice_style_preference: str | None = None,
    ) -> dict:
        ensure_workspace_member(self.db, user_id, workspace_id)
        workspace = self.db.query(WorkspaceModel).filter(WorkspaceModel.id == workspace_id).first()
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if name is not None:
            workspace.name = name.strip()
        if voice_style_preference is not None:
            normalized_style = normalize_voice_style_preference(voice_style_preference)
            if normalized_style not in VOICE_STYLE_PREFERENCES:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported voice style preference")
            workspace.voice_style_preference = normalized_style
        self.db.commit()
        self.db.refresh(workspace)
        return serialize_workspace(workspace)

    def delete(self, user_id: str, workspace_id: str) -> dict:
        workspace = self.db.query(WorkspaceModel).filter(WorkspaceModel.id == workspace_id).first()
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        member = (
            self.db.query(WorkspaceMemberModel)
            .filter(WorkspaceMemberModel.workspace_id == workspace_id, WorkspaceMemberModel.user_id == user_id)
            .first()
        )
        if member is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
        if workspace.owner_id != user_id and member.role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only workspace owners can delete workspaces")

        documents = self.db.query(DocumentModel).filter(DocumentModel.workspace_id == workspace_id).all()
        document_ids = [document.id for document in documents]
        raw_prefixes = {f"raw/{document.uploaded_by}/{workspace_id}" for document in documents}
        extracted_prefixes = {f"extracted/{document.id}" for document in documents}
        wiki_page_ids = [row.id for row in self.db.query(WikiPageModel.id).filter(WikiPageModel.workspace_id == workspace_id).all()]
        chunk_ids = [row.id for row in self.db.query(ChunkModel.id).filter(ChunkModel.workspace_id == workspace_id).all()]
        conversation_ids = [
            row.id for row in self.db.query(ConversationModel.id).filter(ConversationModel.workspace_id == workspace_id).all()
        ]
        message_ids = []
        if conversation_ids:
            message_ids = [
                row.id for row in self.db.query(MessageModel.id).filter(MessageModel.conversation_id.in_(conversation_ids)).all()
            ]

        if self.vector_search is not None:
            self.vector_search.delete_workspace(user_id, workspace_id)

        citation_filters = []
        if message_ids:
            citation_filters.append(CitationModel.message_id.in_(message_ids))
        if chunk_ids:
            citation_filters.append(CitationModel.chunk_id.in_(chunk_ids))
        if document_ids:
            citation_filters.append(CitationModel.document_id.in_(document_ids))
        if wiki_page_ids:
            citation_filters.append(CitationModel.wiki_page_id.in_(wiki_page_ids))
        if citation_filters:
            self.db.query(CitationModel).filter(or_(*citation_filters)).delete(synchronize_session=False)

        self.db.query(VoiceSessionModel).filter(VoiceSessionModel.workspace_id == workspace_id).delete(synchronize_session=False)
        if conversation_ids:
            self.db.query(MessageModel).filter(MessageModel.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        self.db.query(ConversationModel).filter(ConversationModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(ChunkModel).filter(ChunkModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WikiLinkModel).filter(WikiLinkModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WikiAbsorbLogModel).filter(WikiAbsorbLogModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WikiRevisionModel).filter(WikiRevisionModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WikiMaintenanceLogModel).filter(WikiMaintenanceLogModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WikiPageModel).filter(WikiPageModel.workspace_id == workspace_id).delete(synchronize_session=False)
        if document_ids:
            self.db.query(ExtractedDocumentModel).filter(ExtractedDocumentModel.document_id.in_(document_ids)).delete(
                synchronize_session=False
            )
            self.db.query(DocumentVersionModel).filter(DocumentVersionModel.document_id.in_(document_ids)).delete(
                synchronize_session=False
            )
        self.db.query(DocumentModel).filter(DocumentModel.workspace_id == workspace_id).delete(synchronize_session=False)
        self.db.query(WorkspaceMemberModel).filter(WorkspaceMemberModel.workspace_id == workspace_id).delete(
            synchronize_session=False
        )
        self.db.delete(workspace)
        self.db.commit()

        self._delete_storage_prefixes([f"wiki/{workspace_id}", *raw_prefixes, *extracted_prefixes])
        return {"deleted": True, "workspace_id": workspace_id}

    def _delete_storage_prefixes(self, prefixes: list[str]) -> None:
        if self.storage is None:
            return
        for prefix in prefixes:
            self.storage.delete_prefix(prefix)


def serialize_workspace(workspace: WorkspaceModel) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "owner_id": workspace.owner_id,
        "voice_style_preference": workspace.voice_style_preference,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }


def normalize_voice_style_preference(value: str) -> str:
    return (value or "auto").strip().lower().replace("-", "_")
