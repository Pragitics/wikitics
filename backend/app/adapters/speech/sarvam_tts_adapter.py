import base64
from collections.abc import Iterator
import json
from threading import RLock
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect as websocket_connect

from app.shared.metrics import metrics
from app.shared.retry import RetryError, retry_call
from app.shared.user_errors import VOICE_PLAYBACK_UNAVAILABLE


class SarvamTTSAdapter:
    def __init__(
        self,
        api_key: str,
        url: str,
        model: str = "bulbul:v3",
        target_language_code: str = "en-IN",
        speaker: str = "shubh",
        output_audio_codec: str = "mp3",
        pace: float = 1.2,
        temperature: float = 0.45,
        websocket_url: str | None = None,
        websocket_enabled: bool = True,
        websocket_min_buffer_size: int = 50,
        websocket_max_chunk_length: int = 200,
        websocket_output_audio_bitrate: str = "128k",
        websocket_timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.target_language_code = target_language_code
        self.speaker = speaker
        self.output_audio_codec = output_audio_codec
        self.pace = pace
        self.temperature = temperature
        self.websocket_url = websocket_url or default_tts_websocket_url(url)
        self.websocket_enabled = websocket_enabled
        self.websocket_min_buffer_size = websocket_min_buffer_size
        self.websocket_max_chunk_length = websocket_max_chunk_length
        self.websocket_output_audio_bitrate = websocket_output_audio_bitrate
        self.websocket_timeout_seconds = websocket_timeout_seconds
        self.last_stream_transport = "none"
        self._websocket: ClientConnection | None = None
        self._websocket_language_code: str | None = None
        self._websocket_lock = RLock()

    def synthesize(self, text: str) -> bytes:
        def operation() -> bytes:
            if not self.api_key:
                raise RuntimeError(VOICE_PLAYBACK_UNAVAILABLE)

            def call_provider() -> httpx.Response:
                with httpx.Client(timeout=30) as client:
                    response = client.post(
                        self.url,
                        headers={"api-subscription-key": self.api_key},
                        json=self.payload(text),
                    )
                    response.raise_for_status()
                    return response

            try:
                response = retry_call(call_provider, attempts=3, retry_exceptions=(httpx.HTTPError,))
                return decode_audio_response(response)
            except (RetryError, ValueError, KeyError, httpx.HTTPError) as exc:
                raise RuntimeError(VOICE_PLAYBACK_UNAVAILABLE) from exc

        return metrics.time("voice.tts_seconds", operation)

    def stream_synthesize(self, text: str) -> Iterator[bytes]:
        if not self.api_key:
            self.last_stream_transport = "disabled"
            raise RuntimeError(VOICE_PLAYBACK_UNAVAILABLE)
        if self.websocket_enabled and self.websocket_url:
            yielded = False
            try:
                for chunk in self._stream_synthesize_websocket(text):
                    yielded = True
                    self.last_stream_transport = "websocket"
                    yield chunk
                if yielded:
                    return
            except (OSError, TimeoutError, ValueError, WebSocketException):
                self.last_stream_transport = "websocket_failed"
                self.close_websocket()
        try:
            with httpx.Client(timeout=30) as client:
                with client.stream(
                    "POST",
                    self.stream_url(),
                    headers={"api-subscription-key": self.api_key},
                    json=self.payload(text),
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        if chunk:
                            self.last_stream_transport = "http_stream"
                            yield chunk
        except httpx.HTTPError as exc:
            self.last_stream_transport = "http_stream_failed"
            raise RuntimeError(VOICE_PLAYBACK_UNAVAILABLE) from exc

    def close_websocket(self) -> None:
        with self._websocket_lock:
            websocket = self._websocket
            self._websocket = None
            self._websocket_language_code = None
            if websocket is not None:
                try:
                    websocket.close()
                except WebSocketException:
                    return

    def payload(self, text: str) -> dict:
        payload = {
            "text": text[:2500],
            "target_language_code": resolve_tts_language_code(text, self.target_language_code),
            "model": self.model,
            "speaker": self.speaker,
            "pace": self.pace,
            "speech_sample_rate": 24000,
            "output_audio_codec": self.output_audio_codec,
        }
        if self.model == "bulbul:v3":
            payload["temperature"] = self.temperature
        return payload

    def websocket_connect_url(self) -> str:
        parsed = urlparse(self.websocket_url)
        query = dict(parse_qsl(parsed.query))
        query["model"] = self.model
        query["send_completion_event"] = "true"
        return urlunparse(parsed._replace(query=urlencode(query)))

    def websocket_config_message(self, language_code: str | None = None) -> dict:
        data = {
            "speaker": self.speaker,
            "target_language_code": language_code or self.target_language_code,
            "pace": self.pace,
            "min_buffer_size": self.websocket_min_buffer_size,
            "max_chunk_length": self.websocket_max_chunk_length,
            "output_audio_codec": self.output_audio_codec,
            "output_audio_bitrate": self.websocket_output_audio_bitrate,
        }
        if self.model == "bulbul:v3":
            data["temperature"] = self.temperature
        return {"type": "config", "data": data}

    def stream_url(self) -> str:
        parsed = urlparse(self.url)
        if parsed.path.rstrip("/").endswith("/stream"):
            return self.url
        return f"{self.url.rstrip('/')}/stream"

    def _stream_synthesize_websocket(self, text: str) -> Iterator[bytes]:
        language_code = resolve_tts_language_code(text, self.target_language_code)
        with self._websocket_lock:
            websocket = self._ensure_websocket(language_code)
            for chunk in text_message_chunks(text):
                websocket.send(json.dumps({"type": "text", "data": {"text": chunk}}))
            websocket.send(json.dumps({"type": "flush"}))
            yielded = False
            while True:
                message = normalize_tts_websocket_message(
                    websocket.recv(timeout=self.websocket_timeout_seconds),
                )
                if message["type"] == "audio":
                    yielded = True
                    yield message["audio"]
                elif message["type"] == "final":
                    break
                elif message["type"] == "error":
                    raise ValueError(message["message"])
            if not yielded:
                raise ValueError("Sarvam WebSocket TTS returned no audio")

    def _ensure_websocket(self, language_code: str | None = None) -> ClientConnection:
        resolved_language = language_code or self.target_language_code
        if self._websocket is not None and self._websocket_language_code == resolved_language:
            return self._websocket
        if self._websocket is not None:
            try:
                self._websocket.close()
            except WebSocketException:
                pass
            self._websocket = None
            self._websocket_language_code = None
        websocket = websocket_connect(
            self.websocket_connect_url(),
            additional_headers={"api-subscription-key": self.api_key},
            open_timeout=min(self.websocket_timeout_seconds, 10.0),
            ping_interval=20,
            ping_timeout=10,
        )
        websocket.send(json.dumps(self.websocket_config_message(resolved_language)))
        self._websocket = websocket
        self._websocket_language_code = resolved_language
        return websocket


def resolve_tts_language_code(text: str, fallback: str = "en-IN") -> str:
    """Pick a Sarvam TTS language code from native-script content for better pronunciation."""
    counts: dict[str, int] = {}
    for character in text or "":
        code = ord(character)
        if 0x0B80 <= code <= 0x0BFF:
            counts["ta-IN"] = counts.get("ta-IN", 0) + 1
        elif 0x0900 <= code <= 0x097F:
            counts["hi-IN"] = counts.get("hi-IN", 0) + 1
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te-IN"] = counts.get("te-IN", 0) + 1
        elif 0x0C80 <= code <= 0x0CFF:
            counts["kn-IN"] = counts.get("kn-IN", 0) + 1
        elif 0x0D00 <= code <= 0x0D7F:
            counts["ml-IN"] = counts.get("ml-IN", 0) + 1
        elif 0x0980 <= code <= 0x09FF:
            counts["bn-IN"] = counts.get("bn-IN", 0) + 1
        elif 0x0A80 <= code <= 0x0AFF:
            counts["gu-IN"] = counts.get("gu-IN", 0) + 1
        elif 0x0B00 <= code <= 0x0B7F:
            counts["od-IN"] = counts.get("od-IN", 0) + 1
        elif 0x0A00 <= code <= 0x0A7F:
            counts["pa-IN"] = counts.get("pa-IN", 0) + 1
    if not counts:
        return fallback or "en-IN"
    return max(counts.items(), key=lambda item: item[1])[0]


def decode_audio_response(response: httpx.Response) -> bytes:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return response.content
    data = response.json()
    audio = (data.get("audios") or [""])[0]
    return base64.b64decode(audio) if audio else b""


def default_tts_websocket_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    path = parsed.path.rstrip("/")
    if path.endswith("/stream"):
        path = path.removesuffix("/stream")
    if not path.endswith("/ws"):
        path = f"{path}/ws"
    return urlunparse(parsed._replace(scheme=scheme, path=path, query=""))


def text_message_chunks(text: str, max_length: int = 2500) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    return [normalized[index : index + max_length] for index in range(0, len(normalized), max_length)]


def normalize_tts_websocket_message(raw_message) -> dict:
    if isinstance(raw_message, bytes):
        return {"type": "audio", "audio": raw_message}
    if not isinstance(raw_message, str):
        raise ValueError("Unexpected Sarvam TTS WebSocket message")
    payload = json.loads(raw_message)
    message_type = str(payload.get("type") or "").lower()
    data = payload.get("data") or {}
    if message_type == "audio":
        audio = data.get("audio") or data.get("data") or payload.get("audio")
        if not audio:
            raise ValueError("Sarvam TTS WebSocket audio payload missing")
        return {"type": "audio", "audio": base64.b64decode(audio)}
    event_type = str(data.get("event_type") or data.get("event") or payload.get("event_type") or message_type).lower()
    if event_type in {"final", "complete", "completed", "completion"}:
        return {"type": "final"}
    if message_type == "error":
        return {"type": "error", "message": data.get("message") or payload.get("message") or "Sarvam TTS failed"}
    return {"type": "event", "event_type": event_type}
