import httpx


class SarvamSTTAdapter:
    def __init__(self, api_key: str, url: str) -> None:
        self.api_key = api_key
        self.url = url

    def transcribe(self, audio: bytes, content_type: str = "audio/wav") -> str:
        if not self.api_key:
            return ""
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    self.url,
                    headers={"api-subscription-key": self.api_key},
                    files={"file": ("audio.wav", audio, content_type)},
                )
                response.raise_for_status()
                data = response.json()
            return data.get("transcript") or data.get("text") or ""
        except (ValueError, httpx.HTTPError):
            return ""
