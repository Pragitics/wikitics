from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationMessage:
    id: str
    conversation_id: str
    role: str
    content: str
