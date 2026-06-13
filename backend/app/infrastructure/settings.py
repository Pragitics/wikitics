from functools import lru_cache
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Wikitics"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me-in-production"
    access_token_ttl_seconds: int = 86400
    cors_origins: str = "http://localhost:5173"

    database_url: str = "sqlite:///./wikitics.db"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"
    local_storage_root: str = "./storage"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "wikitics"
    s3_access_key_id: str = "wikitics"
    s3_secret_access_key: str = "wikitics-secret"
    s3_region: str = "us-east-1"

    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"

    sarvam_api_key: str = ""
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_stt_stream_url: str = "wss://api.sarvam.ai/speech-to-text/ws"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_mode: str = "transcribe"
    sarvam_stt_language_code: str = "unknown"
    sarvam_stt_stream_sample_rate: int = 16000
    sarvam_stt_input_audio_codec: str = "pcm_s16le"
    sarvam_stt_high_vad_sensitivity: bool = True
    sarvam_stt_vad_signals: bool = True
    sarvam_stt_flush_signal: bool = True
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_language_code: str = "en-IN"
    sarvam_tts_speaker: str = "shubh"
    sarvam_tts_output_audio_codec: str = "mp3"
    sarvam_tts_pace: float = 0.95
    sarvam_tts_temperature: float = 0.45
    sarvam_tts_ws_url: str = "wss://api.sarvam.ai/text-to-speech/ws"
    sarvam_tts_websocket_enabled: bool = True
    sarvam_tts_ws_min_buffer_size: int = 50
    sarvam_tts_ws_max_chunk_length: int = 200
    sarvam_tts_ws_output_audio_bitrate: str = "128k"
    sarvam_tts_ws_timeout_seconds: float = 30.0
    sarvam_document_intelligence_url: str = "https://api.sarvam.ai/doc-digitization/job/v1"
    sarvam_document_intelligence_language: str = "en-IN"
    sarvam_document_intelligence_output_format: str = "md"
    sarvam_document_intelligence_poll_seconds: float = 2.0
    sarvam_document_intelligence_timeout_seconds: float = 120.0
    sarvam_document_intelligence_max_pages: int = 10

    openrouter_api_key: str = ""
    openrouter_base_url: AnyHttpUrl = Field(default="https://openrouter.ai/api/v1")
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_title_model: str = "openai/gpt-4o-mini"
    openrouter_summary_model: str = "openai/gpt-4o-mini"
    openrouter_wiki_model: str = "google/gemini-2.5-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()
