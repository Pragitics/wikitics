from dataclasses import dataclass, field
from typing import Any
from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    GENERATING_WIKI = "generating_wiki"
    WIKI_READY = "wiki_ready"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


SUPPORTED_FILE_TYPES = {"pdf", "docx", "txt", "md", "markdown"}


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    text: str
    headings: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedDocument:
    document_id: str
    filename: str
    file_type: str
    pages: list[ExtractedPage]
    metadata: dict

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())


@dataclass(frozen=True)
class OCRResult:
    pages: list[ExtractedPage]
    metadata: dict
    raw_payload: Any


@dataclass(frozen=True)
class StoredDocument:
    id: str
    workspace_id: str
    uploaded_by: str
    filename: str
    file_type: str
    storage_path: str
    status: DocumentStatus
    checksum: str
