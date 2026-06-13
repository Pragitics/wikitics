from typing import Protocol
from collections.abc import Iterator


class LLMPort(Protocol):
    def answer(self, question: str, context_pack: str) -> str:
        ...


class StreamingLLMPort(LLMPort, Protocol):
    def stream_answer(self, question: str, context_pack: str) -> Iterator[str]:
        ...
