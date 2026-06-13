from typing import Protocol


class DocumentStoragePort(Protocol):
    def save_bytes(self, path: str, content: bytes) -> str:
        ...

    def read_bytes(self, path: str) -> bytes:
        ...

    def save_text(self, path: str, content: str) -> str:
        ...

    def read_text(self, path: str) -> str:
        ...

    def exists(self, path: str) -> bool:
        ...

    def delete(self, path: str) -> None:
        ...

    def delete_prefix(self, prefix: str) -> None:
        ...
