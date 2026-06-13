from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    score: float
    source_type: str
    content: str
    payload: dict


@dataclass(frozen=True)
class Citation:
    document_id: str | None
    filename: str | None
    page_number: int | None
    chunk_id: str | None
    quote: str | None
