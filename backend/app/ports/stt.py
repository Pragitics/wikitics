from typing import Protocol


class STTPort(Protocol):
    def transcribe(self, audio: bytes, content_type: str = "audio/wav") -> str:
        ...
