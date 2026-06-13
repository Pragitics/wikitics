from typing import Protocol

from app.domain.documents.entities import OCRResult


class OCRPort(Protocol):
    def extract_pdf(self, document_id: str, filename: str, content: bytes, page_numbers: list[int]) -> OCRResult | None:
        ...
