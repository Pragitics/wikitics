from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.adapters.llm.openrouter_adapter import OpenRouterLLMAdapter
from app.adapters.ocr.sarvam_document_intelligence_adapter import SarvamDocumentIntelligenceOCRAdapter
from app.adapters.parsers.registry import ParserRegistry
from app.adapters.storage.local_storage_adapter import LocalDocumentStorageAdapter
from app.adapters.voice.livekit_adapter import LiveKitVoiceAdapter
from app.adapters.speech.sarvam_stt_adapter import SarvamSTTAdapter
from app.adapters.speech.sarvam_streaming_stt_adapter import SarvamStreamingSTTBridge
from app.adapters.speech.sarvam_tts_adapter import SarvamTTSAdapter
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import get_db
from app.infrastructure.settings import Settings, get_settings
from app.shared.security import decode_access_token


def settings_dependency() -> Settings:
    return get_settings()


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> UserModel:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    user_id = decode_access_token(token, settings.secret_key)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def storage_dependency(settings: Settings = Depends(settings_dependency)):
    return LocalDocumentStorageAdapter(settings.local_storage_root)


def parser_registry_dependency() -> ParserRegistry:
    return ParserRegistry()


def ocr_dependency(settings: Settings = Depends(settings_dependency)):
    return SarvamDocumentIntelligenceOCRAdapter(
        api_key=settings.sarvam_api_key,
        base_url=settings.sarvam_document_intelligence_url,
        language=settings.sarvam_document_intelligence_language,
        output_format=settings.sarvam_document_intelligence_output_format,
        poll_interval_seconds=settings.sarvam_document_intelligence_poll_seconds,
        timeout_seconds=settings.sarvam_document_intelligence_timeout_seconds,
        max_pages=settings.sarvam_document_intelligence_max_pages,
    )


def llm_dependency(settings: Settings = Depends(settings_dependency)):
    return OpenRouterLLMAdapter(
        api_key=settings.openrouter_api_key,
        base_url=str(settings.openrouter_base_url),
        model=settings.openrouter_model,
        title_model=settings.openrouter_title_model,
        summary_model=settings.openrouter_summary_model,
    )


def livekit_dependency(settings: Settings = Depends(settings_dependency)):
    return LiveKitVoiceAdapter(settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret)


def stt_dependency(settings: Settings = Depends(settings_dependency)):
    return SarvamSTTAdapter(
        api_key=settings.sarvam_api_key,
        url=settings.sarvam_stt_url,
        model=settings.sarvam_stt_model,
        mode=settings.sarvam_stt_mode,
        language_code=settings.sarvam_stt_language_code,
    )


def stt_stream_dependency(settings: Settings = Depends(settings_dependency)):
    return SarvamStreamingSTTBridge(
        api_key=settings.sarvam_api_key,
        url=settings.sarvam_stt_stream_url,
        model=settings.sarvam_stt_model,
        mode=settings.sarvam_stt_mode,
        language_code=settings.sarvam_stt_language_code,
        sample_rate=settings.sarvam_stt_stream_sample_rate,
        input_audio_codec=settings.sarvam_stt_input_audio_codec,
        high_vad_sensitivity=settings.sarvam_stt_high_vad_sensitivity,
        vad_signals=settings.sarvam_stt_vad_signals,
        flush_signal=settings.sarvam_stt_flush_signal,
    )


def tts_dependency(request: Request, settings: Settings = Depends(settings_dependency)):
    config = (
        settings.sarvam_api_key,
        settings.sarvam_tts_url,
        settings.sarvam_tts_model,
        settings.sarvam_tts_language_code,
        settings.sarvam_tts_speaker,
        settings.sarvam_tts_output_audio_codec,
        settings.sarvam_tts_pace,
        settings.sarvam_tts_temperature,
        settings.sarvam_tts_ws_url,
        settings.sarvam_tts_websocket_enabled,
        settings.sarvam_tts_ws_min_buffer_size,
        settings.sarvam_tts_ws_max_chunk_length,
        settings.sarvam_tts_ws_output_audio_bitrate,
        settings.sarvam_tts_ws_timeout_seconds,
    )
    if getattr(request.app.state, "tts_config", None) != config:
        existing_tts = getattr(request.app.state, "tts", None)
        if existing_tts is not None:
            existing_tts.close_websocket()
        request.app.state.tts = SarvamTTSAdapter(
            api_key=settings.sarvam_api_key,
            url=settings.sarvam_tts_url,
            model=settings.sarvam_tts_model,
            target_language_code=settings.sarvam_tts_language_code,
            speaker=settings.sarvam_tts_speaker,
            output_audio_codec=settings.sarvam_tts_output_audio_codec,
            pace=settings.sarvam_tts_pace,
            temperature=settings.sarvam_tts_temperature,
            websocket_url=settings.sarvam_tts_ws_url,
            websocket_enabled=settings.sarvam_tts_websocket_enabled,
            websocket_min_buffer_size=settings.sarvam_tts_ws_min_buffer_size,
            websocket_max_chunk_length=settings.sarvam_tts_ws_max_chunk_length,
            websocket_output_audio_bitrate=settings.sarvam_tts_ws_output_audio_bitrate,
            websocket_timeout_seconds=settings.sarvam_tts_ws_timeout_seconds,
        )
        request.app.state.tts_config = config
    return request.app.state.tts
