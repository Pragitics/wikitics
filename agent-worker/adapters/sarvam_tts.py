import httpx


class SarvamTTSAdapter:
    def __init__(self, api_key: str, url: str) -> None:
        self.api_key = api_key
        self.url = url

    def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            return text.encode("utf-8")
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    self.url,
                    headers={"api-subscription-key": self.api_key},
                    json={"inputs": [text]},
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPError:
            return text.encode("utf-8")
