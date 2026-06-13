import base64
import json
import re
from queue import Queue
from threading import Thread
from time import perf_counter

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.application.voice.service import VoiceSessionService
from app.application.qa.service import QAService, shape_voice_answer
from app.infrastructure.settings import Settings
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import SessionLocal, get_db
from app.interfaces.api.dependencies import (
    embedding_dependency,
    get_current_user,
    livekit_dependency,
    llm_dependency,
    settings_dependency,
    stt_dependency,
    stt_stream_dependency,
    tts_dependency,
    vector_search_dependency,
)
from app.shared.metrics import metrics
from app.shared.security import decode_access_token

router = APIRouter(tags=["voice"])


class VoiceSessionCreateRequest(BaseModel):
    conversation_id: str | None = None


class VoiceTranscriptRequest(BaseModel):
    transcript: str
    voice_style: str = "auto"


def voice_service(db: Session = Depends(get_db), livekit_adapter=Depends(livekit_dependency)) -> VoiceSessionService:
    return VoiceSessionService(db, livekit_adapter)


def qa_service(
    db: Session = Depends(get_db),
    embeddings=Depends(embedding_dependency),
    vector_search=Depends(vector_search_dependency),
    llm=Depends(llm_dependency),
) -> QAService:
    return QAService(db, embeddings, vector_search, llm)


@router.post("/api/workspaces/{workspace_id}/voice/session")
def create_voice_session(
    workspace_id: str,
    payload: VoiceSessionCreateRequest | None = None,
    service: VoiceSessionService = Depends(voice_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.create(user.id, workspace_id, payload.conversation_id if payload else None)


@router.post("/api/voice/session/{session_id}/end")
def end_voice_session(
    session_id: str,
    service: VoiceSessionService = Depends(voice_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.end(user.id, session_id)


@router.get("/api/voice/session/{session_id}")
def get_voice_session(
    session_id: str,
    service: VoiceSessionService = Depends(voice_service),
    user: UserModel = Depends(get_current_user),
) -> dict:
    return service.get(user.id, session_id)


@router.post("/api/voice/session/{session_id}/ask")
def ask_with_voice_transcript(
    session_id: str,
    payload: VoiceTranscriptRequest,
    service: VoiceSessionService = Depends(voice_service),
    qa: QAService = Depends(qa_service),
    tts=Depends(tts_dependency),
    user: UserModel = Depends(get_current_user),
) -> dict:
    session = service.get_model(user.id, session_id)
    trace: dict[str, float] = {}

    def voice_flow() -> tuple[dict, bytes]:
        answer = qa.ask(
            user_id=user.id,
            workspace_id=session.workspace_id,
            question=payload.transcript,
            conversation_id=session.conversation_id,
            mode="voice",
            voice_style_preference=payload.voice_style,
        )
        audio = _time_stage(trace, "tts", lambda: tts.synthesize(answer["answer"]))
        return answer, audio

    answer, audio = metrics.time("voice.end_to_end_seconds", voice_flow)
    return {"transcript": payload.transcript, **voice_audio_payload(answer, audio, trace, tts)}


@router.post("/api/voice/session/{session_id}/ask/stream")
def stream_with_voice_transcript(
    session_id: str,
    payload: VoiceTranscriptRequest,
    service: VoiceSessionService = Depends(voice_service),
    qa: QAService = Depends(qa_service),
    tts=Depends(tts_dependency),
    user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    session = service.get_model(user.id, session_id)
    trace: dict[str, float] = {}
    return StreamingResponse(
        voice_answer_stream_events(payload.transcript.strip(), session, user, qa, tts, trace, payload.voice_style),
        media_type="text/event-stream",
    )


@router.post("/api/voice/session/{session_id}/audio")
async def ask_with_voice_audio(
    session_id: str,
    file: UploadFile = File(...),
    service: VoiceSessionService = Depends(voice_service),
    qa: QAService = Depends(qa_service),
    stt=Depends(stt_dependency),
    tts=Depends(tts_dependency),
    user: UserModel = Depends(get_current_user),
) -> dict:
    session = service.get_model(user.id, session_id)
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="No speech detected")

    trace: dict[str, float] = {}
    transcript = _time_stage(trace, "stt", lambda: stt.transcribe(audio, file.content_type or "audio/webm")).strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="No speech detected")

    def voice_flow() -> tuple[dict, bytes]:
        answer = qa.ask(
            user_id=user.id,
            workspace_id=session.workspace_id,
            question=transcript,
            conversation_id=session.conversation_id,
            mode="voice",
        )
        response_audio = _time_stage(trace, "tts", lambda: tts.synthesize(answer["answer"]))
        return answer, response_audio

    answer, response_audio = metrics.time("voice.end_to_end_seconds", voice_flow)
    return {"transcript": transcript, **voice_audio_payload(answer, response_audio, trace, tts)}


@router.post("/api/voice/session/{session_id}/audio/stream")
async def stream_with_voice_audio(
    session_id: str,
    file: UploadFile = File(...),
    service: VoiceSessionService = Depends(voice_service),
    qa: QAService = Depends(qa_service),
    stt=Depends(stt_dependency),
    tts=Depends(tts_dependency),
    user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    session = service.get_model(user.id, session_id)
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="No speech detected")

    def events():
        trace: dict[str, float] = {}
        transcript = _time_stage(trace, "stt", lambda: stt.transcribe(audio, file.content_type or "audio/webm")).strip()
        if not transcript:
            yield sse_event("error", {"type": "error", "message": "No speech detected"})
            return
        yield sse_event("transcript", {"type": "transcript", "transcript": transcript, "voice_latency": trace})
        yield from voice_answer_stream_events(transcript, session, user, qa, tts, trace)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.websocket("/api/voice/session/{session_id}/stt/stream")
async def stream_stt(
    websocket: WebSocket,
    session_id: str,
    token: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
    service: VoiceSessionService = Depends(voice_service),
    stt_stream=Depends(stt_stream_dependency),
) -> None:
    user = websocket_user(token, db, settings)
    if user is None:
        await websocket.close(code=1008)
        return
    try:
        service.get_model(user.id, session_id)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await stt_stream.proxy(websocket)


def voice_answer_stream_events(
    transcript: str,
    session,
    user: UserModel,
    qa: QAService,
    tts,
    trace: dict[str, float],
    voice_style_preference: str = "auto",
):
    if not transcript:
        yield sse_event("error", {"type": "error", "message": "No speech detected"})
        return
    voice_started = perf_counter()
    audio_mime = audio_mime_for_codec(getattr(tts, "output_audio_codec", "wav"))
    audio_started = False
    audio_bytes = 0
    first_audio_at = None
    spoken_segments: list[str] = []
    pending_text = ""
    final_answer: dict | None = None
    qa_events: Queue = Queue()
    user_id = user.id
    workspace_id = session.workspace_id
    conversation_id = session.conversation_id

    def emit_tts_segment(segment: str):
        nonlocal audio_started, audio_bytes, first_audio_at
        if not segment:
            return
        if not audio_started:
            audio_started = True
            yield sse_event("audio_start", {"type": "audio_start", "audio_mime": audio_mime})
        tts_started = perf_counter()
        for chunk in tts.stream_synthesize(segment):
            now = perf_counter()
            if first_audio_at is None:
                first_audio_at = now
                trace["tts_first_byte"] = now - tts_started
            audio_bytes += len(chunk)
            yield sse_event(
                "audio_delta",
                {
                    "type": "audio_delta",
                    "audio_base64": base64.b64encode(chunk).decode("ascii"),
                    "audio_bytes": len(chunk),
                },
            )
        trace["tts_stream"] = trace.get("tts_stream", 0) + perf_counter() - tts_started
        trace["tts_transport"] = getattr(tts, "last_stream_transport", "unknown")

    def produce_qa_events() -> None:
        db = SessionLocal()
        try:
            threaded_qa = QAService(db, qa.embeddings, qa.vector_search, qa.llm)
            for qa_event in threaded_qa.stream_ask_events(
                user_id=user_id,
                workspace_id=workspace_id,
                question=transcript,
                conversation_id=conversation_id,
                mode="voice",
                voice_style_preference=voice_style_preference,
            ):
                qa_events.put(("event", qa_event))
        except Exception as exc:
            qa_events.put(("error", str(exc)))
        finally:
            db.close()
            qa_events.put(("done", None))

    Thread(target=produce_qa_events, daemon=True).start()

    while True:
        message_type, event = qa_events.get()
        if message_type == "done":
            break
        if message_type == "error":
            yield sse_event("error", {"type": "error", "message": "Voice failed", "detail": event})
            return
        event_type = event.get("type")
        if event_type == "context_ready":
            yield sse_event("context_ready", event)
            continue
        if event_type == "answer_delta":
            pending_text += str(event.get("delta") or "")
            while len(spoken_segments) < voice_segment_limit(transcript):
                segment, pending_text = pop_ready_voice_segment(pending_text, transcript)
                if not segment:
                    break
                spoken_segments.append(segment)
                yield from emit_tts_segment(segment)
            continue
        if event_type == "final":
            final_answer = event
            break

    if final_answer is None:
        yield sse_event("error", {"type": "error", "message": "Voice failed"})
        return

    remaining_segment = remaining_voice_segment(str(final_answer.get("answer") or ""), spoken_segments)
    if remaining_segment:
        spoken_segments.append(remaining_segment)
        yield from emit_tts_segment(remaining_segment)
    if first_audio_at is not None:
        trace["first_audio_from_voice_start"] = first_audio_at - voice_started
    trace["tts_transport"] = getattr(tts, "last_stream_transport", trace.get("tts_transport", "unknown"))
    answer_event = {
        "type": "answer",
        "transcript": transcript,
        "answer": final_answer["answer"],
        "conversation_id": final_answer["conversation_id"],
        "message_id": final_answer.get("message_id"),
        "latency": final_answer.get("latency", {}),
        "context_stats": final_answer.get("context_stats", {}),
    }
    yield sse_event("answer", answer_event)
    payload = voice_audio_payload(
        final_answer,
        b"",
        trace,
        tts,
        audio_bytes_override=audio_bytes,
    )
    payload.pop("audio_base64", None)
    payload["transcript"] = transcript
    yield sse_event("final", {"type": "final", **payload})


def pop_ready_voice_segment(buffer: str, transcript: str) -> tuple[str | None, str]:
    match = re.search(r"(?<=[.!?])\s+", buffer)
    if match:
        end = match.end()
    elif buffer.rstrip().endswith((".", "!", "?")):
        end = len(buffer)
    else:
        return None, buffer
    raw_segment = buffer[:end].strip()
    pending = buffer[end:].lstrip()
    return shape_voice_answer(raw_segment, transcript), pending


def voice_segment_limit(transcript: str) -> int:
    transcript_lower = transcript.lower()
    wants_one_sentence = "one sentence" in transcript_lower or "short" in transcript_lower or "quick" in transcript_lower
    teaching_request = bool(re.search(r"\b(learn|understand|explain|teach|why|how|walk me through)\b", transcript_lower))
    return 1 if wants_one_sentence or not teaching_request else 2


def remaining_voice_segment(answer: str, spoken_segments: list[str]) -> str:
    final_text = compact_text(answer)
    spoken = compact_text(" ".join(spoken_segments))
    if not final_text:
        return ""
    if not spoken:
        return final_text
    if final_text.startswith(spoken):
        return final_text[len(spoken) :].lstrip(" .,!?:;")
    return ""


def compact_text(value: str) -> str:
    return " ".join(value.split())


def websocket_user(token: str, db: Session, settings: Settings) -> UserModel | None:
    user_id = decode_access_token(token, settings.secret_key)
    if user_id is None:
        return None
    return db.query(UserModel).filter(UserModel.id == user_id).first()


def voice_audio_payload(
    answer: dict,
    audio: bytes,
    trace: dict | None = None,
    tts=None,
    audio_bytes_override: int | None = None,
) -> dict:
    payload = {"audio_bytes": len(audio) if audio_bytes_override is None else audio_bytes_override, **answer}
    if trace is not None:
        payload["voice_latency"] = {
            **trace,
            "qa": answer.get("latency", {}),
            "total_observed": numeric_total(trace) + numeric_total(answer.get("latency") or {}),
        }
    if audio:
        payload["audio_base64"] = base64.b64encode(audio).decode("ascii")
        payload["audio_mime"] = audio_mime_for_codec(getattr(tts, "output_audio_codec", "wav"))
    return payload


def _time_stage(trace: dict[str, float], key: str, func):
    start = perf_counter()
    try:
        return func()
    finally:
        trace[key] = perf_counter() - start


def numeric_total(values: dict) -> float:
    return sum(value for value in values.values() if isinstance(value, int | float))


def audio_mime_for_codec(codec: str) -> str:
    normalized = codec.strip().lower()
    if normalized in {"mp3", "mpeg"}:
        return "audio/mpeg"
    if normalized == "aac":
        return "audio/aac"
    if normalized == "opus":
        return "audio/ogg"
    if normalized == "flac":
        return "audio/flac"
    if normalized in {"linear16", "mulaw", "alaw"}:
        return "audio/wav"
    return "audio/wav"


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
