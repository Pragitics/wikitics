from typing import Protocol


class EmbeddingPort(Protocol):
    def embed(self, text: str) -> list[float]:
        ...
