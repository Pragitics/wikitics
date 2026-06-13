import httpx

from app.shared.metrics import metrics
from app.shared.retry import RetryError, retry_call
from app.shared.user_errors import SPEECH_RECOGNITION_UNAVAILABLE


class SarvamSTTAdapter:
    def __init__(
        self,
        api_key: str,
        url: str,
        model: str = "saaras:v3",
        mode: str = "transcribe",
        language_code: str = "unknown",
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.mode = mode
        self.language_code = language_code

    def transcribe(self, audio: bytes, content_type: str = "audio/wav") -> str:
        def operation() -> str:
            if not self.api_key:
                raise RuntimeError(SPEECH_RECOGNITION_UNAVAILABLE)
            normalized_content_type = normalize_content_type(content_type)
            files = {
                "file": (
                    f"audio.{extension_for_content_type(normalized_content_type)}",
                    audio,
                    normalized_content_type,
                )
            }

            def call_provider() -> httpx.Response:
                with httpx.Client(timeout=30) as client:
                    response = client.post(
                        self.url,
                        headers={"api-subscription-key": self.api_key},
                        files=files,
                        data={
                            "model": self.model,
                            "mode": self.mode,
                            "language_code": self.language_code,
                        },
                    )
                    response.raise_for_status()
                    return response

            try:
                response = retry_call(call_provider, attempts=3, retry_exceptions=(httpx.HTTPError,))
                data = response.json()
                return data.get("transcript") or data.get("text") or ""
            except (RetryError, ValueError, httpx.HTTPError) as exc:
                raise RuntimeError(SPEECH_RECOGNITION_UNAVAILABLE) from exc

        return metrics.time("voice.stt_seconds", operation)


def normalize_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in {"audio/webm", "video/webm"}:
        return "audio/webm"
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return "audio/mpeg"
    if normalized in {"audio/mp4", "audio/x-m4a"}:
        return "audio/mp4"
    if normalized in {"audio/ogg", "application/ogg"}:
        return "audio/ogg"
    if normalized in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "audio/wav"
    if normalized in {"audio/aiff", "audio/x-aiff"}:
        return "audio/aiff"
    return "audio/webm"


def extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in {"audio/webm", "video/webm"}:
        return "webm"
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    if normalized in {"audio/mp4", "audio/x-m4a"}:
        return "m4a"
    if normalized in {"audio/ogg", "application/ogg"}:
        return "ogg"
    if normalized in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "wav"
    if normalized in {"audio/aiff", "audio/x-aiff"}:
        return "aiff"
    return "webm"
