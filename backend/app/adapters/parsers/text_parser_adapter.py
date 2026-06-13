from app.domain.documents.entities import ExtractedDocument, ExtractedPage


class TextParserAdapter:
    supported_types = {"txt", "md", "markdown"}

    def parse(self, document_id: str, filename: str, file_type: str, content: bytes) -> ExtractedDocument:
        text = content.decode("utf-8", errors="replace")
        headings = [
            line.strip("# ").strip()
            for line in text.splitlines()
            if line.strip().startswith("#") and line.strip("# ").strip()
        ]
        return ExtractedDocument(
            document_id=document_id,
            filename=filename,
            file_type=file_type,
            pages=[ExtractedPage(page_number=1, text=text, headings=headings)],
            metadata={"parser": "text", "line_count": len(text.splitlines())},
        )
