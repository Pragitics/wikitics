from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceSession:
    id: str
    conversation_id: str
    workspace_id: str
    room_name: str
    status: str
    livekit_url: str
    livekit_token: str
