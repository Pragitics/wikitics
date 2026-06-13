from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.adapters.llm.openrouter_wiki_generator_adapter import OpenRouterWikiGeneratorAdapter
from app.application.documents.service import DocumentService
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import get_db
from app.interfaces.api.dependencies import (
    embedding_dependency,
    get_current_user,
    ocr_dependency,
    parser_registry_dependency,
    storage_dependency,
    vector_search_dependency,
    settings_dependency,
)
from app.infrastructure.settings import Settings

router = APIRouter(tags=["documents"])


def document_service(
    db: Session = Depends(get_db),
    storage=Depends(storage_dependency),
    parser_registry=Depends(parser_registry_dependency),
    ocr=Depends(ocr_dependency),
    embeddings=Depends(embedding_dependency),
    vector_search=Depends(vector_search_dependency),
    settings: Settings = Depends(settings_dependency),
) -> DocumentService:
    return DocumentService(
        db,
        storage,
        parser_registry,
        embeddings,
        vector_search,
        ocr=ocr,
        wiki_generator=OpenRouterWikiGeneratorAdapter(
            settings.openrouter_api_key,
            str(settings.openrouter_base_url),
            settings.openrouter_wiki_model,
        ),
    )


@router.post("/api/workspaces/{workspace_id}/documents")
async def upload_document(
    workspace_id: str,
    file: UploadFile,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return await service.upload(user.id, workspace_id, file)


@router.get("/api/workspaces/{workspace_id}/documents")
def list_documents(
    workspace_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    return service.list_documents(user.id, workspace_id)


@router.get("/api/documents/{document_id}")
def get_document(
    document_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.get_document(user.id, document_id)


@router.get("/api/documents/{document_id}/source")
def get_document_source(
    document_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.source(user.id, document_id)


@router.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.delete_document(user.id, document_id)


@router.post("/api/documents/{document_id}/process")
def process_document(
    document_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.process(user.id, document_id)


@router.get("/api/documents/{document_id}/status")
def document_status(
    document_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.status(user.id, document_id)


@router.post("/api/workspaces/{workspace_id}/index/rebuild")
def rebuild_workspace_index(
    workspace_id: str,
    service: DocumentService = Depends(document_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.rebuild_index(user.id, workspace_id)
