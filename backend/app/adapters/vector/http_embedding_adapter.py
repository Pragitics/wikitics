import httpx

from app.adapters.vector.local_embedding_adapter import LocalEmbeddingAdapter
from app.shared.retry import retry_call


class HTTPEmbeddingAdapter:
    def __init__(self, api_key: str, url: str, model: str, dimension: int = 64) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.fallback = LocalEmbeddingAdapter(dimension=dimension)

    def embed(self, text: str) -> list[float]:
        if not self.api_key:
            return self.fallback.embed(text)
        payload = {"model": self.model, "input": text}

        def call_provider() -> httpx.Response:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                return response

        data = retry_call(call_provider, attempts=3, retry_exceptions=(httpx.HTTPError,)).json()
        vector = data.get("data", [{}])[0].get("embedding")
        if not isinstance(vector, list):
            return self.fallback.embed(text)
        return [float(value) for value in vector]
