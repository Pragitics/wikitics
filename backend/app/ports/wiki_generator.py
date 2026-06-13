from typing import Protocol

from app.domain.documents.entities import ExtractedDocument
from app.domain.wiki.entities import WikiBundle, WikiPage


class WikiGeneratorPort(Protocol):
    def generate(
        self,
        workspace_id: str,
        document: ExtractedDocument,
        existing_pages: list[WikiPage] | None = None,
    ) -> WikiBundle:
        ...
