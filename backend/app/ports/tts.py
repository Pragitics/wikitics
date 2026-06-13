from typing import Protocol


class TTSPort(Protocol):
    def synthesize(self, text: str) -> bytes:
        ...
