import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.application.qa.service import QAService
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import get_db
from app.interfaces.api.dependencies import get_current_user, llm_dependency, storage_dependency

router = APIRouter(tags=["qa"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: str | None = None
    document_ids: list[str] | None = None
    answer_style: str = "concise"
    voice_style: str = "auto"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    document_ids: list[str] | None = None


def qa_service(
    db: Session = Depends(get_db),
    storage=Depends(storage_dependency),
    llm=Depends(llm_dependency),
) -> QAService:
    return QAService(db, storage, llm)


@router.post("/api/workspaces/{workspace_id}/ask")
def ask_question(
    workspace_id: str,
    payload: AskRequest,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.ask(
        user_id=user.id,
        workspace_id=workspace_id,
        question=payload.question,
        conversation_id=payload.conversation_id,
        document_ids=payload.document_ids,
        voice_style_preference=payload.voice_style,
    )


@router.post("/api/workspaces/{workspace_id}/ask/stream")
def stream_question(
    workspace_id: str,
    payload: AskRequest,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    events = service.stream_ask_events(
        user_id=user.id,
        workspace_id=workspace_id,
        question=payload.question,
        conversation_id=payload.conversation_id,
        document_ids=payload.document_ids,
        voice_style_preference=payload.voice_style,
    )
    return StreamingResponse(_sse(events), media_type="text/event-stream")


@router.post("/api/workspaces/{workspace_id}/retrieval/search")
def retrieval_search(
    workspace_id: str,
    payload: SearchRequest,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    return service.search(user.id, workspace_id, payload.query, document_ids=payload.document_ids)


@router.get("/api/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.get_conversation(user.id, conversation_id)


@router.get("/api/workspaces/{workspace_id}/conversations")
def list_conversations(
    workspace_id: str,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> list[dict]:
    return service.list_conversations(user.id, workspace_id)


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    service: QAService = Depends(qa_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.delete_conversation(user.id, conversation_id)


def _sse(events):
    for event in events:
        event_type = event.get("type", "message")
        yield f"event: {event_type}\ndata: {json.dumps(event, default=str)}\n\n"
