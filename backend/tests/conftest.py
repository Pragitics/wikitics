import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_STORAGE = Path("./test-storage")
TEST_DB = Path("./test-wikitics.db")

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["LOCAL_STORAGE_ROOT"] = str(TEST_STORAGE)
os.environ["SECRET_KEY"] = "test-secret"
os.environ["CORS_ORIGINS"] = "http://testserver"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["SARVAM_API_KEY"] = ""

from app.infrastructure.db.models import Base
from app.infrastructure.db.session import engine
from app.adapters.llm.openrouter_wiki_generator_adapter import OpenRouterWikiGeneratorAdapter
from app.adapters.llm.openrouter_wiki_maintenance_adapter import OpenRouterWikiMaintenanceAdapter
from app.domain.wiki.entities import WikiBundle, WikiPage
from app.interfaces.api.dependencies import llm_dependency
from app.main import app
from app.shared.ids import new_id


@pytest.fixture()
def client():
    yield from _test_client()


@pytest.fixture()
def non_raising_client():
    yield from _test_client(raise_server_exceptions=False)


def _test_client(raise_server_exceptions: bool = True):
    original_wiki_generate = OpenRouterWikiGeneratorAdapter.generate
    original_wiki_merge = OpenRouterWikiMaintenanceAdapter.merge_pages
    OpenRouterWikiGeneratorAdapter.generate = _fake_wiki_generate
    OpenRouterWikiMaintenanceAdapter.merge_pages = _fake_wiki_merge
    app.dependency_overrides[llm_dependency] = lambda: TestLLM()
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
    if TEST_STORAGE.exists():
        shutil.rmtree(TEST_STORAGE)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with TestClient(app, raise_server_exceptions=raise_server_exceptions) as test_client:
            yield test_client
    finally:
        OpenRouterWikiGeneratorAdapter.generate = original_wiki_generate
        OpenRouterWikiMaintenanceAdapter.merge_pages = original_wiki_merge
        app.dependency_overrides.pop(llm_dependency, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()
        if TEST_STORAGE.exists():
            shutil.rmtree(TEST_STORAGE)


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "password123", "name": "Owner"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def workspace_id(client, auth_headers):
    response = client.get("/api/workspaces", headers=auth_headers)
    assert response.status_code == 200
    return response.json()[0]["id"]


class TestLLM:
    api_key = "test-key"

    def answer(self, question: str, context_pack: str) -> str:
        haystack = f"{question}\n{context_pack}".lower()
        if "late payment penalty" in haystack:
            return "The late payment penalty is 2 percent."
        if "refund window" in haystack and "14 days" in haystack:
            return "The refund window is 14 days."
        return "The documents say the relevant detail is available in the workspace wiki."

    def stream_answer(self, question: str, context_pack: str):
        yield self.answer(question, context_pack)

    def title(self, messages: list[dict]) -> str:
        first = next((str(message.get("content") or "") for message in messages if message.get("role") == "user"), "")
        words = [word.strip(".,:;!?") for word in first.split() if word.strip(".,:;!?")]
        words = [word for word in words if word.lower() not in {"this"}]
        return " ".join(words[:4]) or "New chat"

    def summarize_conversation(self, existing_summary: str, messages: list[dict]) -> str:
        return "User goals: answer questions from the workspace wiki."


def _fake_wiki_generate(self, workspace_id: str, document, existing_pages=None) -> WikiBundle:
    existing_pages = existing_pages or []
    title = _title_from_filename(document.filename)
    content_text = "\n\n".join(page.text for page in document.pages if page.text).strip()
    content = f"# {title}\n\n{content_text}" if content_text else f"# {title}"
    summary = " ".join(content_text.split())[:220] or title
    matching_page = next((page for page in existing_pages if _normalize_title(page.title) == _normalize_title(title)), None)
    if matching_page is not None:
        content = f"{matching_page.content.rstrip()}\n\n## Additional Evidence From {document.filename}\n\n{content_text}".strip()
        page = WikiPage(
            id=matching_page.id,
            workspace_id=workspace_id,
            title=matching_page.title,
            path=matching_page.path,
            content=content,
            summary=summary,
            created_from_document_ids=sorted(set((matching_page.created_from_document_ids or []) + [document.document_id])),
            target_page_id=matching_page.id,
        )
    else:
        page = WikiPage(
            id=new_id(),
            workspace_id=workspace_id,
            title=title,
            path=f"{_slugify(title)}.md",
            content=content,
            summary=summary,
            created_from_document_ids=[document.document_id],
        )
    return WikiBundle(
        pages=[page],
        index_content=f"# Wikitics Index\n\n- [{page.title}]({page.path}) - {page.summary}\n",
        backlinks={page.path: []},
        absorb_log={"document_id": document.document_id, "strategy": "test-openrouter-fake"},
    )


def _fake_wiki_merge(self, primary, duplicate) -> dict:
    content = "\n\n".join(part for part in [primary.content.strip(), duplicate.content.strip()] if part)
    return {"content": content, "summary": primary.summary or duplicate.summary or ""}


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(word.capitalize() for word in stem.split()) or "Document"


def _slugify(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-") or "document"


def _normalize_title(value: str) -> str:
    return " ".join(str(value or "").lower().split())
