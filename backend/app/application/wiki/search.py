import json
import re
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.domain.retrieval.entities import SearchResult
from app.infrastructure.db.models import DocumentModel, WikiPageModel
from app.shared.metrics import metrics


class WikiSearch:
    def __init__(self, db: Session, storage) -> None:
        self.db = db
        self.storage = storage

    def search(
        self,
        workspace_id: str,
        query: str,
        document_ids: list[str] | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        normalized_query = _normalize_text(query)
        terms = [term for term in normalized_query.split() if len(term) > 2][:12]
        document_filenames = self._document_filenames(workspace_id)
        allowed_document_ids = set(document_ids or [])
        pages = (
            self.db.query(WikiPageModel)
            .filter(WikiPageModel.workspace_id == workspace_id)
            .order_by(WikiPageModel.updated_at.desc())
            .all()
        )

        page_results = [
            self._page_result(page, terms, document_filenames)
            for page in pages
            if not allowed_document_ids or allowed_document_ids.intersection(page.created_from_document_ids or [])
        ]
        page_results = [result for result in page_results if result.score > 0 or not terms]
        if not page_results and pages:
            page_results = [
                self._page_result(page, [], document_filenames, base_score=0.2)
                for page in pages[: min(max_results, 5)]
                if not allowed_document_ids or allowed_document_ids.intersection(page.created_from_document_ids or [])
            ]

        backlinks = self.read_backlinks(workspace_id)
        expanded = self._expand_backlinks(page_results, pages, backlinks, document_filenames, allowed_document_ids)
        projection_results = [] if allowed_document_ids else self._projection_results(workspace_id, terms)
        merged = _merge_results([*page_results, *expanded, *projection_results])
        metrics.observe("wiki.search_results", len(merged))
        return merged[:max_results]

    def read_index(self, workspace_id: str) -> str:
        path = str(PurePosixPath("wiki") / workspace_id / "INDEX.md")
        return self.storage.read_text(path) if self.storage.exists(path) else ""

    def read_backlinks(self, workspace_id: str) -> dict[str, list[str]]:
        path = str(PurePosixPath("wiki") / workspace_id / "_backlinks.json")
        if not self.storage.exists(path):
            return {}
        try:
            payload = json.loads(self.storage.read_text(path))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): [str(item) for item in value] for key, value in payload.items() if isinstance(value, list)}

    def _page_result(
        self,
        page: WikiPageModel,
        terms: list[str],
        document_filenames: dict[str, str],
        base_score: float = 0.0,
    ) -> SearchResult:
        text = _normalize_text(" ".join([page.title, page.summary or "", page.content or ""]))
        title_text = _normalize_text(page.title)
        summary_text = _normalize_text(page.summary or "")
        overlap = sum(1 for term in terms if term in text)
        title_overlap = sum(1 for term in terms if term in title_text)
        summary_overlap = sum(1 for term in terms if term in summary_text)
        score = base_score or overlap * 0.1 + title_overlap * 0.25 + summary_overlap * 0.15
        linked_documents = page.created_from_document_ids or []
        return SearchResult(
            chunk_id=f"wiki-page:{page.id}",
            score=score,
            source_type="wiki",
            content=page.content,
            payload={
                "workspace_id": page.workspace_id,
                "wiki_page_id": page.id,
                "source_type": "wiki",
                "title": page.title,
                "heading": page.title,
                "path": page.path,
                "linked_raw_documents": linked_documents,
                "linked_raw_document_filenames": {
                    document_id: document_filenames.get(document_id, document_id) for document_id in linked_documents
                },
                "content_preview": page.content[:300],
            },
        )

    def _projection_results(self, workspace_id: str, terms: list[str]) -> list[SearchResult]:
        results = []
        index_content = self.read_index(workspace_id)
        if index_content:
            score = _text_score(index_content, terms, base_score=0.12)
            results.append(
                SearchResult(
                    chunk_id=f"wiki-index:{workspace_id}",
                    score=score,
                    source_type="wiki_index",
                    content=index_content,
                    payload={
                        "workspace_id": workspace_id,
                        "source_type": "wiki_index",
                        "title": "Workspace Index",
                        "heading": "INDEX.md",
                        "path": "INDEX.md",
                    },
                )
            )
        backlinks = self.read_backlinks(workspace_id)
        if backlinks:
            content = json.dumps(backlinks, indent=2)
            score = _text_score(content, terms, base_score=0.08)
            results.append(
                SearchResult(
                    chunk_id=f"wiki-backlinks:{workspace_id}",
                    score=score,
                    source_type="wiki_backlinks",
                    content=content,
                    payload={
                        "workspace_id": workspace_id,
                        "source_type": "wiki_backlinks",
                        "title": "Workspace Backlinks",
                        "heading": "_backlinks.json",
                        "path": "_backlinks.json",
                    },
                )
            )
        return results

    def _expand_backlinks(
        self,
        selected_results: list[SearchResult],
        pages: list[WikiPageModel],
        backlinks: dict[str, list[str]],
        document_filenames: dict[str, str],
        allowed_document_ids: set[str],
    ) -> list[SearchResult]:
        if not selected_results or not backlinks:
            return []
        selected_paths = {str(result.payload.get("path") or "") for result in selected_results}
        related_paths = set()
        for target, sources in backlinks.items():
            if target in selected_paths:
                related_paths.update(sources)
            if selected_paths.intersection(sources):
                related_paths.add(target)
        existing_ids = {str(result.payload.get("wiki_page_id") or "") for result in selected_results}
        page_by_path = {page.path: page for page in pages}
        expanded = []
        for path in sorted(related_paths):
            page = page_by_path.get(path)
            if page is None or page.id in existing_ids:
                continue
            if allowed_document_ids and not allowed_document_ids.intersection(page.created_from_document_ids or []):
                continue
            expanded.append(self._page_result(page, [], document_filenames, base_score=0.35))
        return expanded

    def _document_filenames(self, workspace_id: str) -> dict[str, str]:
        return {
            row.id: row.filename
            for row in self.db.query(DocumentModel.id, DocumentModel.filename)
            .filter(DocumentModel.workspace_id == workspace_id)
            .all()
        }


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _text_score(content: str, terms: list[str], base_score: float) -> float:
    if not terms:
        return base_score
    normalized = _normalize_text(content)
    overlap = sum(1 for term in terms if term in normalized)
    return base_score + overlap * 0.05


def _merge_results(results: list[SearchResult]) -> list[SearchResult]:
    merged: dict[str, SearchResult] = {}
    for result in results:
        existing = merged.get(result.chunk_id)
        if existing is None or result.score > existing.score:
            merged[result.chunk_id] = result
    return sorted(merged.values(), key=lambda result: result.score, reverse=True)
