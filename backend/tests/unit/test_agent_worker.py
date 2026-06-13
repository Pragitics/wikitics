import sys
from pathlib import Path


AGENT_WORKER_PATH = Path(__file__).resolve().parents[3] / "agent-worker"
sys.path.insert(0, str(AGENT_WORKER_PATH))

from agents.wikitics_voice_agent import WikiticsVoiceAgent  # noqa: E402


class FakeQAClient:
    def ask(self, token: str, workspace_id: str, question: str, conversation_id: str | None = None) -> dict:
        return {"answer": f"Answer for {question}", "conversation_id": conversation_id or "conv-1"}


class FakeTTS:
    def synthesize(self, text: str) -> bytes:
        return text.encode("utf-8")


def test_agent_worker_handles_transcript_with_qa_and_tts():
    agent = WikiticsVoiceAgent(FakeQAClient(), FakeTTS())

    result = agent.handle_transcript("token", "workspace-1", "What is due?")

    assert result["answer"]["answer"] == "Answer for What is due?"
    assert result["audio_bytes"] > 0
