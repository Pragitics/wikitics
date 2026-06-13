import re

from app.domain.retrieval.entities import Chunk
from app.domain.wiki.entities import WikiPage
from app.shared.ids import new_id


def chunk_wiki_page(page: WikiPage, user_id: str, document_filenames: dict[str, str] | None = None) -> list[Chunk]:
    sections = _markdown_sections(page.content)
    chunks = []
    linked_documents = list(page.created_from_document_ids or [])
    metadata = {"linked_raw_documents": linked_documents}
    if document_filenames:
        linked_filenames = {
            document_id: document_filenames[document_id]
            for document_id in linked_documents
            if document_id in document_filenames
        }
        if linked_filenames:
            metadata["linked_raw_document_filenames"] = linked_filenames
    for heading, content in sections:
        if not content.strip():
            continue
        chunks.append(
            Chunk(
                id=new_id(),
                workspace_id=page.workspace_id,
                user_id=user_id,
                source_type="wiki",
                wiki_page_id=page.id,
                title=page.title,
                heading=heading,
                path=page.path,
                content=content.strip(),
                metadata=dict(metadata),
            )
        )
    return chunks


def chunk_wiki_index(workspace_id: str, user_id: str, content: str) -> list[Chunk]:
    if not content.strip():
        return []
    return [
        Chunk(
            id=new_id(),
            workspace_id=workspace_id,
            user_id=user_id,
            source_type="wiki_index",
            title="Workspace Index",
            heading="INDEX.md",
            path="wiki/INDEX.md",
            content=content.strip(),
            metadata={"projection": "workspace_index"},
        )
    ]


def chunk_wiki_backlinks(workspace_id: str, user_id: str, backlinks: dict[str, list[str]]) -> list[Chunk]:
    if not backlinks:
        return []
    lines = ["Workspace backlinks and concept map"]
    for target, sources in sorted(backlinks.items()):
        linked_sources = ", ".join(sorted(sources)) if sources else "none"
        lines.append(f"{target} <- {linked_sources}")
    return [
        Chunk(
            id=new_id(),
            workspace_id=workspace_id,
            user_id=user_id,
            source_type="wiki_backlinks",
            title="Workspace Backlinks",
            heading="Concept map",
            path="wiki/_backlinks.json",
            content="\n".join(lines),
            metadata={"projection": "workspace_backlinks"},
        )
    ]


def _markdown_sections(content: str) -> list[tuple[str, str]]:
    lines = content.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Summary"
    current_lines: list[str] = []
    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))
    return [(heading, "\n".join(section_lines)) for heading, section_lines in sections]

