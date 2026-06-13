import httpx


class OpenRouterLLMAdapter:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str) -> str:
        if not self.api_key:
            return prompt[:500]
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, ValueError, httpx.HTTPError):
            return prompt[:500]
