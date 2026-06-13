from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.application.workspaces.access import ensure_workspace_member
from app.infrastructure.db.models import ConversationModel, VoiceSessionModel
from app.shared.ids import new_id


class VoiceSessionService:
    def __init__(self, db: Session, livekit_adapter) -> None:
        self.db = db
        self.livekit_adapter = livekit_adapter

    def create(self, user_id: str, workspace_id: str, conversation_id: str | None = None) -> dict:
        ensure_workspace_member(self.db, user_id, workspace_id)
        if conversation_id:
            conversation = self.db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            ensure_workspace_member(self.db, user_id, conversation.workspace_id)
        else:
            conversation = ConversationModel(id=new_id(), workspace_id=workspace_id, user_id=user_id, mode="voice")
            self.db.add(conversation)
            self.db.flush()
        session_id = new_id()
        room_name = f"wikitics-{user_id[:8]}-{conversation.id[:8]}-{session_id[:8]}"
        token = self.livekit_adapter.token_for_room(identity=user_id, room_name=room_name)
        session = VoiceSessionModel(
            id=session_id,
            conversation_id=conversation.id,
            workspace_id=workspace_id,
            user_id=user_id,
            livekit_room_name=room_name,
            status="active",
        )
        self.db.add(session)
        self.db.commit()
        return {
            "session_id": session.id,
            "conversation_id": conversation.id,
            "room_name": room_name,
            "livekit_token": token,
            "livekit_url": self.livekit_adapter.url,
            "status": session.status,
        }

    def get(self, user_id: str, session_id: str) -> dict:
        session = self._get_session(user_id, session_id)
        return serialize_voice_session(session, self.livekit_adapter.url)

    def end(self, user_id: str, session_id: str) -> dict:
        session = self._get_session(user_id, session_id)
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc)
        self.db.commit()
        return serialize_voice_session(session, self.livekit_adapter.url)

    def _get_session(self, user_id: str, session_id: str) -> VoiceSessionModel:
        session = self.db.query(VoiceSessionModel).filter(VoiceSessionModel.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice session not found")
        ensure_workspace_member(self.db, user_id, session.workspace_id)
        return session

    def get_model(self, user_id: str, session_id: str) -> VoiceSessionModel:
        return self._get_session(user_id, session_id)


def serialize_voice_session(session: VoiceSessionModel, livekit_url: str) -> dict:
    return {
        "session_id": session.id,
        "conversation_id": session.conversation_id,
        "room_name": session.livekit_room_name,
        "livekit_url": livekit_url,
        "status": session.status,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    }
