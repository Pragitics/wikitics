from typing import Protocol

from app.domain.retrieval.entities import Chunk, SearchResult


class VectorSearchPort(Protocol):
    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        ...

    def search(self, vector: list[float], filters: dict, limit: int = 8) -> list[SearchResult]:
        ...

    def delete_workspace(self, user_id: str, workspace_id: str) -> None:
        ...

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        ...

    def delete_wiki_pages(self, user_id: str, workspace_id: str, page_ids: list[str]) -> None:
        ...
