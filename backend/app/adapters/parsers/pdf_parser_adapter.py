from io import BytesIO

from app.domain.documents.entities import ExtractedDocument, ExtractedPage


class PDFParserAdapter:
    supported_types = {"pdf"}

    def parse(self, document_id: str, filename: str, file_type: str, content: bytes) -> ExtractedDocument:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        pages = []
        text_lengths = []
        ocr_required_pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text_lengths.append(len(text.strip()))
            if not text.strip():
                ocr_required_pages.append(index)
            pages.append(ExtractedPage(page_number=index, text=text, headings=[]))
        return ExtractedDocument(
            document_id=document_id,
            filename=filename,
            file_type=file_type,
            pages=pages or [ExtractedPage(page_number=1, text="", headings=[])],
            metadata={
                "parser": "pypdf",
                "page_count": len(pages),
                "page_text_lengths": text_lengths,
                "ocr_required_pages": ocr_required_pages,
                "ocr_status": "required_not_configured" if ocr_required_pages else "not_required",
            },
        )
