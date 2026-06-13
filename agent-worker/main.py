import logging
import time

from adapters.fastapi_rag_client import FastAPIRAGClient
from adapters.sarvam_tts import SarvamTTSAdapter
from agents.wikitics_voice_agent import WikiticsVoiceAgent
from config import AgentSettings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    settings = AgentSettings()
    rag_client = FastAPIRAGClient(settings.backend_api_url)
    WikiticsVoiceAgent(
        rag_client=rag_client,
        tts=SarvamTTSAdapter(settings.sarvam_api_key, settings.sarvam_tts_url),
    )
    logging.info("Wikitics voice agent worker started")
    while True:
        try:
            health = rag_client.health()
            logging.info("Backend health: %s", health.get("status"))
        except Exception as exc:
            logging.warning("Backend health check failed: %s", exc)
        time.sleep(settings.agent_poll_seconds)


if __name__ == "__main__":
    main()
