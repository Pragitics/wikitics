from qdrant_client import QdrantClient, models

from app.domain.retrieval.entities import Chunk, SearchResult
from app.shared.metrics import metrics
from app.shared.retry import retry_call


class QdrantVectorSearchAdapter:
    def __init__(self, url: str, collection: str, vector_size: int) -> None:
        self.client = QdrantClient(url=url)
        self.collection = collection
        self.vector_size = vector_size
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = self.client.get_collections().collections
        if any(collection.name == self.collection for collection in collections):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
        )

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
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
                    "content": chunk.content,
                }
            )
            points.append(models.PointStruct(id=chunk.id, vector=vector, payload=payload))
        if points:
            metrics.time(
                "qdrant.upsert_seconds",
                lambda: retry_call(lambda: self.client.upsert(collection_name=self.collection, points=points), attempts=3),
            )

    def search(self, vector: list[float], filters: dict, limit: int = 8) -> list[SearchResult]:
        if "user_id" not in filters or "workspace_id" not in filters:
            raise ValueError("Vector search requires user_id and workspace_id filters")
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filters.items()
                if value is not None
            ]
        )
        if hasattr(self.client, "query_points"):
            response = metrics.time(
                "qdrant.search_seconds",
                lambda: retry_call(
                    lambda: self.client.query_points(
                        collection_name=self.collection,
                        query=vector,
                        query_filter=query_filter,
                        limit=limit,
                    ),
                    attempts=3,
                ),
            )
            points = response.points
        else:
            points = metrics.time(
                "qdrant.search_seconds",
                lambda: retry_call(
                    lambda: self.client.search(
                        collection_name=self.collection,
                        query_vector=vector,
                        query_filter=query_filter,
                        limit=limit,
                    ),
                    attempts=3,
                ),
            )
        return [
            SearchResult(
                chunk_id=str(point.id),
                score=float(point.score),
                source_type=point.payload.get("source_type", ""),
                content=point.payload.get("content", point.payload.get("content_preview", "")),
                payload=point.payload,
            )
            for point in points
        ]

    def delete_workspace(self, user_id: str, workspace_id: str) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                        models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                    ]
                )
            ),
        )

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=chunk_ids),
        )

    def delete_wiki_pages(self, user_id: str, workspace_id: str, page_ids: list[str]) -> None:
        if not page_ids:
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                        models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                        models.FieldCondition(key="wiki_page_id", match=models.MatchAny(any=page_ids)),
                    ]
                )
            ),
        )
