from dataclasses import dataclass, field


@dataclass(frozen=True)
class WikiPage:
    id: str
    workspace_id: str
    title: str
    path: str
    content: str
    summary: str
    created_from_document_ids: list[str] = field(default_factory=list)
    target_page_id: str | None = None


@dataclass(frozen=True)
class WikiLink:
    source_page_id: str
    target_page_id: str
    link_type: str = "related"


@dataclass(frozen=True)
class WikiGraph:
    pages: list[WikiPage]
    links: list[WikiLink] = field(default_factory=list)

    def backlinks(self) -> dict[str, list[str]]:
        path_by_id = {page.id: page.path for page in self.pages}
        backlinks = {page.path: [] for page in self.pages}
        for link in self.links:
            source_path = path_by_id.get(link.source_page_id)
            target_path = path_by_id.get(link.target_page_id)
            if source_path and target_path:
                backlinks.setdefault(target_path, []).append(source_path)
        return backlinks


@dataclass(frozen=True)
class WikiBundle:
    pages: list[WikiPage]
    index_content: str
    backlinks: dict[str, list[str]]
    absorb_log: dict
    links: list[WikiLink] = field(default_factory=list)
