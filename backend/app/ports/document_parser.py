from typing import Protocol

from app.domain.documents.entities import ExtractedDocument


class DocumentParserPort(Protocol):
    supported_types: set[str]

    def parse(self, document_id: str, filename: str, file_type: str, content: bytes) -> ExtractedDocument:
        ...
