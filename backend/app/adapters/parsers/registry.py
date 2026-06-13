from app.adapters.parsers.docx_parser_adapter import DocxParserAdapter
from app.adapters.parsers.pdf_parser_adapter import PDFParserAdapter
from app.adapters.parsers.text_parser_adapter import TextParserAdapter
from app.ports.document_parser import DocumentParserPort


class ParserRegistry:
    def __init__(self, parsers: list[DocumentParserPort] | None = None) -> None:
        self.parsers = parsers or [TextParserAdapter(), PDFParserAdapter(), DocxParserAdapter()]

    def parser_for(self, file_type: str) -> DocumentParserPort:
        normalized = file_type.lower().lstrip(".")
        for parser in self.parsers:
            if normalized in parser.supported_types:
                return parser
        raise ValueError(f"Unsupported file type: {file_type}")
