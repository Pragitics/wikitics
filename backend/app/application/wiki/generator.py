import re

from app.domain.documents.entities import ExtractedDocument
from app.domain.wiki.entities import WikiBundle, WikiPage
from app.shared.ids import new_id


class DeterministicWikiGenerator:
    def generate(
        self,
        workspace_id: str,
        document: ExtractedDocument,
        existing_pages: list[WikiPage] | None = None,
    ) -> WikiBundle:
        title = _title_from_filename(document.filename)
        summary = _summarize(document.full_text)
        references = "\n".join(
            f"- {document.filename}, page {page.page_number}" for page in document.pages if page.text.strip()
        )
        existing_page = _find_existing_page(existing_pages or [], title)
        page_title = existing_page.title if existing_page else title
        page_path = existing_page.path if existing_page else f"wiki/{_slugify(page_title)}.md"
        content = _page_content(
            title=page_title,
            summary=summary,
            body=document.full_text[:6000] or "No extractable text was found.",
            references=references or f"- {document.filename}",
            existing_content=existing_page.content if existing_page else None,
            filename=document.filename,
            document_id=document.document_id,
        )
        page = WikiPage(
            id=new_id(),
            workspace_id=workspace_id,
            title=page_title,
            path=page_path,
            content=content,
            summary=summary,
            created_from_document_ids=[document.document_id],
            target_page_id=existing_page.id if existing_page else None,
        )
        index_content = f"# Wikitics Index\n\n- [{page_title}]({page.path}) - {summary}\n"
        backlinks = {page.path: []}
        absorb_log = {
            "document_id": document.document_id,
            "filename": document.filename,
            "generated_pages": [page.path],
            "strategy": "deterministic-local",
            "edit_strategy": "update_existing_page" if existing_page else "create_new_page",
        }
        return WikiBundle(pages=[page], index_content=index_content, backlinks=backlinks, absorb_log=absorb_log)


def _title_from_filename(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    title = re.sub(r"[_-]+", " ", base).strip().title()
    return title or "Uploaded Document"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "uploaded-document"


def _summarize(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "No extractable text was found in this document."
    return normalized[:500] + ("..." if len(normalized) > 500 else "")


def _find_existing_page(existing_pages: list[WikiPage], title: str) -> WikiPage | None:
    normalized = _normalize(title)
    for page in existing_pages:
        if _normalize(page.title) == normalized:
            return page
    return None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _page_content(
    title: str,
    summary: str,
    body: str,
    references: str,
    existing_content: str | None,
    filename: str,
    document_id: str,
) -> str:
    generated = "\n\n".join(
        [
            f"# {title}",
            "## Summary",
            summary,
            "## Key Extracted Content",
            body,
            "## Source References",
            references,
        ]
    )
    if not existing_content:
        return generated
    marker = f"<!-- source-document: {document_id} -->"
    if marker in existing_content:
        return existing_content
    return (
        existing_content.rstrip()
        + "\n\n"
        + f"## Additional Evidence From {filename}\n"
        + body
        + "\n\n## Source References\n"
        + references
        + f"\n\n{marker}"
    )
