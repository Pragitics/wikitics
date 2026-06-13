from adapters.fastapi_rag_client import FastAPIRAGClient
from adapters.sarvam_tts import SarvamTTSAdapter


class WikiticsVoiceAgent:
    def __init__(self, rag_client: FastAPIRAGClient, tts: SarvamTTSAdapter) -> None:
        self.rag_client = rag_client
        self.tts = tts

    def handle_transcript(
        self,
        token: str,
        workspace_id: str,
        transcript: str,
        conversation_id: str | None = None,
    ) -> dict:
        answer = self.rag_client.ask(token, workspace_id, transcript, conversation_id=conversation_id)
        audio = self.tts.synthesize(answer["answer"])
        return {"answer": answer, "audio_bytes": len(audio)}
