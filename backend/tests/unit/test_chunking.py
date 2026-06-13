from app.application.wiki.chunking import chunk_wiki_page
from app.domain.wiki.entities import WikiPage


def test_wiki_chunking_uses_markdown_headings():
    page = WikiPage(
        id="wiki-1",
        workspace_id="workspace-1",
        title="Payment Terms",
        path="wiki/payment-terms.md",
        content="# Payment Terms\n\n## Due Date\nPay in 30 days.\n\n## Penalty\nLate fee applies.",
        summary="Payment summary",
        created_from_document_ids=["doc-1"],
    )

    chunks = chunk_wiki_page(page, "user-1")

    assert [chunk.heading for chunk in chunks] == ["Due Date", "Penalty"]
    assert all(chunk.source_type == "wiki" for chunk in chunks)


def test_wiki_chunking_includes_linked_document_filenames():
    page = WikiPage(
        id="wiki-1",
        workspace_id="workspace-1",
        title="Payment Terms",
        path="wiki/payment-terms.md",
        content="# Payment Terms\n\n## Due Date\nPay in 30 days.",
        summary="Payment summary",
        created_from_document_ids=["doc-1", "doc-2"],
    )

    chunks = chunk_wiki_page(page, "user-1", document_filenames={"doc-1": "agreement.txt", "doc-2": "appendix.pdf"})

    assert chunks[0].metadata["linked_raw_documents"] == ["doc-1", "doc-2"]
    assert chunks[0].metadata["linked_raw_document_filenames"] == {
        "doc-1": "agreement.txt",
        "doc-2": "appendix.pdf",
    }
