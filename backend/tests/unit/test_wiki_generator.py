from app.application.wiki.generator import DeterministicWikiGenerator
from app.domain.documents.entities import ExtractedDocument, ExtractedPage
from app.domain.wiki.entities import WikiGraph, WikiLink, WikiPage


def test_wiki_generator_creates_index_backlinks_and_absorb_log():
    document = ExtractedDocument(
        document_id="doc-1",
        filename="payment_terms.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Invoices are due within 30 days.")],
        metadata={},
    )

    bundle = DeterministicWikiGenerator().generate("workspace-1", document)

    assert bundle.pages[0].title == "Payment Terms"
    assert "Payment Terms" in bundle.index_content
    assert bundle.backlinks == {bundle.pages[0].path: []}
    assert bundle.absorb_log["document_id"] == "doc-1"


def test_wiki_generator_updates_existing_page_when_title_matches():
    document = ExtractedDocument(
        document_id="doc-2",
        filename="payment_terms.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Invoices also require finance review.")],
        metadata={},
    )
    existing = WikiPage(
        "page-1",
        "workspace-1",
        "Payment Terms",
        "wiki/payment-terms.md",
        "# Payment Terms\n\n## Summary\nInvoices are due within 30 days.",
        "Invoices are due within 30 days.",
    )

    bundle = DeterministicWikiGenerator().generate("workspace-1", document, existing_pages=[existing])

    assert bundle.pages[0].target_page_id == "page-1"
    assert bundle.pages[0].path == "wiki/payment-terms.md"
    assert "Additional Evidence From payment_terms.txt" in bundle.pages[0].content


def test_wiki_graph_builds_backlinks_from_links():
    first = WikiPage("page-1", "workspace-1", "First", "wiki/first.md", "# First", "First")
    second = WikiPage("page-2", "workspace-1", "Second", "wiki/second.md", "# Second", "Second")

    graph = WikiGraph(pages=[first, second], links=[WikiLink(source_page_id="page-1", target_page_id="page-2")])

    assert graph.backlinks()["wiki/second.md"] == ["wiki/first.md"]
