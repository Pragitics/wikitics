from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    id: str
    workspace_id: str
    user_id: str
    source_type: str
    content: str
    document_id: str | None = None
    wiki_page_id: str | None = None
    title: str | None = None
    heading: str | None = None
    path: str | None = None
    page_number: int | None = None
    metadata: dict = field(default_factory=dict)


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
