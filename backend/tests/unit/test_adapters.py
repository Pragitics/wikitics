import json
from base64 import b64encode

import httpx

from app.adapters.llm.openrouter_adapter import OpenRouterLLMAdapter
from app.adapters.llm.openrouter_wiki_generator_adapter import OpenRouterWikiGeneratorAdapter
from app.adapters.llm.openrouter_wiki_maintenance_adapter import OpenRouterWikiMaintenanceAdapter
from app.adapters.speech.sarvam_stt_adapter import SarvamSTTAdapter
from app.adapters.speech.sarvam_streaming_stt_adapter import (
    SarvamStreamingSTTBridge,
    audio_message,
    normalize_provider_message,
)
from app.adapters.speech import sarvam_tts_adapter
from app.adapters.speech.sarvam_tts_adapter import SarvamTTSAdapter, default_tts_websocket_url, text_message_chunks
from app.adapters.voice.livekit_adapter import LiveKitVoiceAdapter
from app.domain.wiki.entities import WikiPage
from app.interfaces.api.routes.voice_routes import audio_mime_for_codec
from app.domain.documents.entities import ExtractedDocument, ExtractedPage
from app.infrastructure.db.models import WikiPageModel


class FakeClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response

    def stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeStreamResponse(self.response)


class FakeSequentialClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.responses:
            raise AssertionError("No fake responses left")
        return self.responses.pop(0)


class FakeStreamResponse:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, tb):
        return False


def test_sarvam_stt_adapter_uses_transcript_response(monkeypatch):
    response = httpx.Response(200, json={"transcript": "hello"}, request=httpx.Request("POST", "https://example.test/stt"))
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    transcript = SarvamSTTAdapter("key", "https://example.test/stt").transcribe(b"audio")

    assert transcript == "hello"
    assert fake_client.calls[0][1]["data"]["model"] == "saaras:v3"
    assert fake_client.calls[0][1]["data"]["mode"] == "transcribe"


def test_sarvam_streaming_stt_bridge_builds_connection_url():
    bridge = SarvamStreamingSTTBridge("key", "wss://example.test/stt/ws", language_code="en-IN")

    url = bridge.connect_url()

    assert url.startswith("wss://example.test/stt/ws?")
    assert "language-code=en-IN" in url
    assert "model=saaras%3Av3" in url
    assert "input_audio_codec=pcm_s16le" in url
    assert "vad_signals=true" in url
    assert "flush_signal=true" in url


def test_sarvam_streaming_stt_audio_and_response_messages():
    assert audio_message("YWJj") == {
        "audio": {
            "data": "YWJj",
            "sample_rate": 16000,
            "encoding": "pcm_s16le",
        }
    }
    assert normalize_provider_message(
        json.dumps(
            {
                "type": "data",
                "data": {
                    "transcript": "hello",
                    "metrics": {"processing_latency": 0.07},
                },
            }
        )
    ) == {
        "type": "transcript",
        "transcript": "hello",
        "metrics": {"processing_latency": 0.07},
    }
    assert normalize_provider_message(json.dumps({"type": "speech_start"})) == {"type": "speech_start"}


def test_sarvam_tts_adapter_returns_audio_content(monkeypatch):
    response = httpx.Response(
        200,
        json={"audios": [b64encode(b"audio-bytes").decode("ascii")]},
        request=httpx.Request("POST", "https://example.test/tts"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    audio = SarvamTTSAdapter("key", "https://example.test/tts").synthesize("hello")

    assert audio == b"audio-bytes"
    assert fake_client.calls[0][1]["json"]["model"] == "bulbul:v3"
    assert fake_client.calls[0][1]["json"]["target_language_code"] == "en-IN"
    assert fake_client.calls[0][1]["json"]["speaker"] == "shubh"
    assert fake_client.calls[0][1]["json"]["output_audio_codec"] == "mp3"


def test_audio_mime_for_tts_codec():
    assert audio_mime_for_codec("mp3") == "audio/mpeg"
    assert audio_mime_for_codec("wav") == "audio/wav"


def test_sarvam_tts_adapter_streams_audio_content(monkeypatch):
    response = httpx.Response(
        200,
        content=b"audio-stream",
        request=httpx.Request("POST", "https://example.test/tts/stream"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    chunks = list(SarvamTTSAdapter("key", "https://example.test/tts").stream_synthesize("hello"))

    assert chunks == [b"audio-stream"]
    assert fake_client.calls[0][0][1] == "https://example.test/tts/stream"


def test_sarvam_tts_adapter_streams_audio_from_websocket(monkeypatch):
    websocket = FakeWebSocket(
        [
            json.dumps({"type": "audio", "data": {"audio": b64encode(b"ws-audio").decode("ascii")}}),
            json.dumps({"type": "event", "data": {"event_type": "final"}}),
        ]
    )
    connect_calls = []

    def fake_connect(*args, **kwargs):
        connect_calls.append((args, kwargs))
        return websocket

    monkeypatch.setattr(sarvam_tts_adapter, "websocket_connect", fake_connect)

    adapter = SarvamTTSAdapter("key", "https://example.test/text-to-speech")
    chunks = list(adapter.stream_synthesize("hello"))

    assert chunks == [b"ws-audio"]
    assert connect_calls[0][0][0].startswith("wss://example.test/text-to-speech/ws?")
    assert connect_calls[0][1]["additional_headers"]["api-subscription-key"] == "key"
    assert websocket.sent[0]["type"] == "config"
    assert websocket.sent[0]["data"]["output_audio_codec"] == "mp3"
    assert websocket.sent[1] == {"type": "text", "data": {"text": "hello"}}
    assert websocket.sent[2] == {"type": "flush"}


def test_sarvam_tts_adapter_falls_back_to_http_stream_when_websocket_fails(monkeypatch):
    response = httpx.Response(
        200,
        content=b"http-audio",
        request=httpx.Request("POST", "https://example.test/tts/stream"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(sarvam_tts_adapter, "websocket_connect", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    chunks = list(SarvamTTSAdapter("key", "https://example.test/tts").stream_synthesize("hello"))

    assert chunks == [b"http-audio"]
    assert fake_client.calls[0][0][1] == "https://example.test/tts/stream"


def test_sarvam_tts_websocket_helpers():
    assert default_tts_websocket_url("https://example.test/text-to-speech/stream") == "wss://example.test/text-to-speech/ws"
    assert text_message_chunks("  hello   world  ") == ["hello world"]
    assert text_message_chunks("a" * 2501) == ["a" * 2500, "a"]


def test_livekit_token_contains_room_claim():
    token = LiveKitVoiceAdapter("ws://localhost:7880", "devkey", "secret").token_for_room("user-1", "room-1")
    header, payload, signature = token.split(".")

    assert header
    assert signature
    decoded = json.loads(_decode_segment(payload))
    assert decoded["room"] == "room-1"
    assert decoded["iss"] == "devkey"


def test_openrouter_title_uses_configured_cheap_model(monkeypatch):
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "Payment Terms"}}]},
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    title = OpenRouterLLMAdapter("key", "https://example.test", "expensive-model", title_model="cheap-model").title(
        [{"role": "user", "content": "What is the payment penalty?"}]
    )

    assert title == "Payment Terms"
    assert fake_client.calls[0][1]["json"]["model"] == "cheap-model"


def test_openrouter_summary_uses_configured_cheap_model(monkeypatch):
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "User goals: compare support options."}}]},
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    summary = OpenRouterLLMAdapter(
        "key",
        "https://example.test",
        "expensive-model",
        title_model="title-model",
        summary_model="summary-cheap-model",
    ).summarize_conversation("", [{"role": "user", "content": "What support options are mentioned?"}])

    assert summary == "User goals: compare support options."
    assert fake_client.calls[0][1]["json"]["model"] == "summary-cheap-model"


def test_openrouter_answer_allows_detailed_responses(monkeypatch):
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "Detailed answer"}}]},
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    answer = OpenRouterLLMAdapter("key", "https://example.test", "answer-model").answer(
        "Explain the workflow in detail",
        "Relevant Wiki Sections:\nThe workflow has many steps.",
    )

    payload = fake_client.calls[0][1]["json"]
    assert answer == "Detailed answer"
    assert payload["max_tokens"] >= 700
    assert "Do not force answers into one line" in payload["messages"][0]["content"]


def test_openrouter_wiki_generator_uses_configured_model(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "pages": [
                                    {
                                        "existing_page_id": "wiki-existing-1",
                                        "title": "Invoice Workflow",
                                        "summary": "Invoice workflow summary.",
                                        "content": "# Invoice Workflow\n\nInvoices are reviewed.",
                                    }
                                ],
                                "index_content": "# Index",
                                "backlinks": {},
                                "absorb_log": {"strategy": "llm"},
                            }
                        )
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)
    document = ExtractedDocument(
        document_id="doc-1",
        filename="invoice.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Invoices are reviewed.")],
        metadata={},
    )
    existing = WikiPage(
        id="wiki-existing-1",
        workspace_id="workspace-1",
        title="Invoice Workflow",
        path="wiki/invoice-workflow.md",
        content="# Invoice Workflow\n\nInvoices are reviewed.",
        summary="Invoice workflow summary.",
    )

    bundle = OpenRouterWikiGeneratorAdapter("key", "https://example.test", "wiki-model").generate(
        "workspace-1",
        document,
        existing_pages=[existing],
    )

    assert bundle.pages[0].title == "Invoice Workflow"
    assert bundle.pages[0].target_page_id == "wiki-existing-1"
    assert bundle.pages[0].path == "wiki/invoice-workflow.md"
    assert fake_client.calls[0][1]["json"]["model"] == "wiki-model"
    assert "workspace_wiki_overview" in fake_client.calls[0][1]["json"]["messages"][1]["content"]


def test_openrouter_wiki_generator_normalizes_backlink_objects_in_direct_mode(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "pages": [
                                    {
                                        "title": "Invoice Workflow",
                                        "summary": "Invoice workflow summary.",
                                        "content": "# Invoice Workflow\n\nInvoices are reviewed.",
                                        "path": "invoice-workflow",
                                    },
                                    {
                                        "title": "Server Support",
                                        "summary": "Server support summary.",
                                        "content": "# Server Support\n\nEscalations are handled here.",
                                        "path": "server-support",
                                    },
                                ],
                                "backlinks": {
                                    "Server Support": [{"title": "Invoice Workflow"}],
                                    "invoice-workflow": [{"path": "server-support"}],
                                },
                                "absorb_log": {"strategy": "llm"},
                            }
                        )
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)
    document = ExtractedDocument(
        document_id="doc-1",
        filename="invoice.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Invoices and escalations are reviewed.")],
        metadata={},
    )

    bundle = OpenRouterWikiGeneratorAdapter("key", "https://example.test", "wiki-model").generate(
        "workspace-1",
        document,
        existing_pages=[],
    )

    assert bundle.backlinks["server-support"] == ["invoice-workflow"]
    assert bundle.backlinks["invoice-workflow"] == ["server-support"]


def test_openrouter_wiki_generator_agent_can_list_read_and_write_multiple_pages(monkeypatch):
    responses = [
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"action": "list_pages"})}}]},
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"action": "read_page", "page_id": "wiki-existing-1"})
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "write_page",
                                    "existing_page_id": "wiki-existing-1",
                                    "title": "Invoice Workflow",
                                    "path": "invoice-workflow",
                                    "summary": "Invoices are reviewed and escalated.",
                                    "content": "# Invoice Workflow\n\nInvoices are reviewed and escalated.",
                                }
                            )
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "write_page",
                                    "existing_page_id": None,
                                    "title": "Server Support",
                                    "path": "server-support",
                                    "summary": "Server support covers uptime checks.",
                                    "content": "# Server Support\n\nServer support covers uptime checks.",
                                }
                            )
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "finish",
                                    "backlinks": {
                                        "invoice-workflow": [],
                                        "server-support": ["invoice-workflow"],
                                    },
                                    "notes": "Updated invoice workflow and added server support page.",
                                }
                            )
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
    ]
    fake_client = FakeSequentialClient(responses)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)
    document = ExtractedDocument(
        document_id="doc-1",
        filename="ops.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Ops covers invoices and server support.")],
        metadata={},
    )
    existing = WikiPage(
        id="wiki-existing-1",
        workspace_id="workspace-1",
        title="Invoice Workflow",
        path="invoice-workflow",
        content="# Invoice Workflow\n\nInvoices are reviewed.",
        summary="Invoice workflow summary.",
        created_from_document_ids=["seed-doc"],
    )

    bundle = OpenRouterWikiGeneratorAdapter("key", "https://example.test", "wiki-model").generate(
        "workspace-1",
        document,
        existing_pages=[existing],
    )

    assert len(bundle.pages) == 2
    invoice = next(page for page in bundle.pages if page.title == "Invoice Workflow")
    support = next(page for page in bundle.pages if page.title == "Server Support")
    assert invoice.target_page_id == "wiki-existing-1"
    assert "reviewed and escalated" in invoice.content
    assert support.target_page_id is None
    assert support.path == "server-support"
    assert bundle.backlinks["server-support"] == ["invoice-workflow"]
    assert bundle.absorb_log["strategy"] == "openrouter-agent"
    assert len(fake_client.calls) == 5


def test_openrouter_wiki_generator_agent_rejects_finish_before_write(monkeypatch):
    responses = [
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"action": "finish", "notes": "done"})}}]},
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "write_page",
                                    "existing_page_id": None,
                                    "title": "Support Workflow",
                                    "path": "support-workflow",
                                    "summary": "Support workflow covers escalation.",
                                    "content": "# Support Workflow\n\nSupport workflow covers escalation.",
                                }
                            )
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "finish",
                                    "backlinks": {"support-workflow": []},
                                    "notes": "Created support workflow page.",
                                }
                            )
                        }
                    }
                ]
            },
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
    ]
    fake_client = FakeSequentialClient(responses)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)
    document = ExtractedDocument(
        document_id="doc-1",
        filename="support.txt",
        file_type="txt",
        pages=[ExtractedPage(page_number=1, text="Support workflow covers escalation.")],
        metadata={},
    )
    existing = WikiPage(
        id="wiki-existing-1",
        workspace_id="workspace-1",
        title="Existing Notes",
        path="existing-notes",
        content="# Existing Notes\n\nCurrent workspace notes.",
        summary="Current workspace notes.",
    )

    bundle = OpenRouterWikiGeneratorAdapter("key", "https://example.test", "wiki-model").generate(
        "workspace-1",
        document,
        existing_pages=[existing],
    )

    assert len(bundle.pages) == 1
    assert bundle.pages[0].title == "Support Workflow"
    assert bundle.absorb_log["actions"][0]["tool_result"]["error"].startswith("No wiki pages have been created")
    assert len(fake_client.calls) == 3


def test_openrouter_wiki_maintenance_merge_uses_configured_model(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "content": "# Invoice Workflow\n\nInvoices are reviewed and reconciled.",
                                "summary": "Invoices are reviewed and reconciled.",
                            }
                        )
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )
    fake_client = FakeClient(response)
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)
    primary = WikiPageModel(title="Invoice Workflow", summary="Invoices are reviewed.", content="# Invoice Workflow\n\nInvoices are reviewed.")
    duplicate = WikiPageModel(title="Invoice Workflow", summary="Invoices are reconciled.", content="# Invoice Workflow\n\nInvoices are reconciled.")

    merged = OpenRouterWikiMaintenanceAdapter("key", "https://example.test", "wiki-maintenance-model").merge_pages(primary, duplicate)

    assert merged["summary"] == "Invoices are reviewed and reconciled."
    assert "reviewed and reconciled" in merged["content"]
    assert fake_client.calls[0][1]["json"]["model"] == "wiki-maintenance-model"


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.sent = []
        self.closed = False

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self, timeout=None) -> str:
        if not self.messages:
            raise TimeoutError
        return self.messages.pop(0)

    def close(self) -> None:
        self.closed = True


def _decode_segment(segment: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(segment + ("=" * (-len(segment) % 4)))
