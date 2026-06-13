import asyncio
import json
from urllib.parse import urlencode

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
import websockets
from websockets.exceptions import WebSocketException


class SarvamStreamingSTTBridge:
    def __init__(
        self,
        api_key: str,
        url: str,
        model: str = "saaras:v3",
        mode: str = "transcribe",
        language_code: str = "unknown",
        sample_rate: int = 16000,
        input_audio_codec: str = "pcm_s16le",
        high_vad_sensitivity: bool = True,
        vad_signals: bool = True,
        flush_signal: bool = True,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.mode = mode
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.input_audio_codec = input_audio_codec
        self.high_vad_sensitivity = high_vad_sensitivity
        self.vad_signals = vad_signals
        self.flush_signal = flush_signal

    def connect_url(self) -> str:
        query = urlencode(
            {
                "language-code": self.language_code,
                "model": self.model,
                "mode": self.mode,
                "sample_rate": str(self.sample_rate),
                "input_audio_codec": self.input_audio_codec,
                "high_vad_sensitivity": str(self.high_vad_sensitivity).lower(),
                "vad_signals": str(self.vad_signals).lower(),
                "flush_signal": str(self.flush_signal).lower(),
            }
        )
        return f"{self.url}?{query}"

    async def proxy(self, client: WebSocket) -> None:
        if not self.api_key:
            await client.send_json({"type": "error", "message": "Streaming STT unavailable"})
            return
        try:
            async with websockets.connect(
                self.connect_url(),
                additional_headers={"Api-Subscription-Key": self.api_key},
                compression=None,
            ) as provider:
                client_to_provider = asyncio.create_task(self._client_to_provider(client, provider))
                provider_to_client = asyncio.create_task(self._provider_to_client(provider, client))
                done, pending = await asyncio.wait(
                    {client_to_provider, provider_to_client},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except (WebSocketDisconnect, WebSocketException, OSError, json.JSONDecodeError):
            await send_json_if_connected(client, {"type": "error", "message": "Streaming STT failed"})

    async def _client_to_provider(self, client: WebSocket, provider) -> None:
        while True:
            message = await client.receive_json()
            message_type = message.get("type")
            if message_type == "audio":
                await provider.send(
                    json.dumps(
                        audio_message(
                            audio_base64=str(message.get("audio_base64") or ""),
                            sample_rate=int(message.get("sample_rate") or self.sample_rate),
                            encoding=str(message.get("encoding") or self.input_audio_codec),
                        )
                    )
                )
            elif message_type == "flush":
                await provider.send(json.dumps({"type": "flush"}))
            elif message_type == "stop":
                return

    async def _provider_to_client(self, provider, client: WebSocket) -> None:
        async for raw_message in provider:
            await client.send_json(normalize_provider_message(raw_message))


def audio_message(audio_base64: str, sample_rate: int = 16000, encoding: str = "pcm_s16le") -> dict:
    return {
        "audio": {
            "data": audio_base64,
            "sample_rate": sample_rate,
            "encoding": encoding,
        }
    }


def normalize_provider_message(raw_message: str | bytes) -> dict:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")
    payload = json.loads(raw_message)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_type = payload.get("type")
    if message_type in {"speech_start", "speech_end"}:
        return {"type": message_type}
    transcript = data.get("transcript") or data.get("text") or payload.get("transcript") or payload.get("text")
    if transcript:
        return {
            "type": "transcript",
            "transcript": transcript,
            "metrics": data.get("metrics") or payload.get("metrics") or {},
        }
    return {"type": message_type or "provider", "payload": payload}


async def send_json_if_connected(client: WebSocket, payload: dict) -> None:
    try:
        await client.send_json(payload)
    except RuntimeError:
        return
