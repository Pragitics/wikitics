import math

from app.domain.retrieval.entities import Chunk, SearchResult


class LocalVectorSearchAdapter:
    def __init__(self) -> None:
        self.points: dict[str, tuple[list[float], Chunk]] = {}

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.points[chunk.id] = (vector, chunk)

    def search(self, vector: list[float], filters: dict, limit: int = 8) -> list[SearchResult]:
        if "user_id" not in filters or "workspace_id" not in filters:
            raise ValueError("Vector search requires user_id and workspace_id filters")
        results = []
        for stored_vector, chunk in self.points.values():
            if not self._matches(chunk, filters):
                continue
            score = self._cosine(vector, stored_vector)
            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    score=score,
                    source_type=chunk.source_type,
                    content=chunk.content,
                    payload=self._payload(chunk),
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

    def delete_workspace(self, user_id: str, workspace_id: str) -> None:
        self.points = {
            key: value
            for key, value in self.points.items()
            if value[1].user_id != user_id or value[1].workspace_id != workspace_id
        }

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self.points.pop(chunk_id, None)

    def delete_wiki_pages(self, user_id: str, workspace_id: str, page_ids: list[str]) -> None:
        allowed = set(page_ids)
        self.points = {
            key: value
            for key, value in self.points.items()
            if value[1].user_id != user_id
            or value[1].workspace_id != workspace_id
            or value[1].wiki_page_id not in allowed
        }

    def _matches(self, chunk: Chunk, filters: dict) -> bool:
        for key, value in filters.items():
            if value is None:
                continue
            if getattr(chunk, key, chunk.metadata.get(key)) != value:
                return False
        return True

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _payload(self, chunk: Chunk) -> dict:
        payload = dict(chunk.metadata)
        payload.update(
            {
                "user_id": chunk.user_id,
                "workspace_id": chunk.workspace_id,
                "document_id": chunk.document_id,
                "wiki_page_id": chunk.wiki_page_id,
                "source_type": chunk.source_type,
                "title": chunk.title,
                "heading": chunk.heading,
                "path": chunk.path,
                "page_number": chunk.page_number,
                "content_preview": chunk.content[:300],
            }
        )
        return payload
