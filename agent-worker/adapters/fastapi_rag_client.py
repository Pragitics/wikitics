import httpx


class FastAPIRAGClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        with httpx.Client(timeout=5) as client:
            response = client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    def ask(self, token: str, workspace_id: str, question: str, conversation_id: str | None = None) -> dict:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.base_url}/api/workspaces/{workspace_id}/ask",
                headers={"Authorization": f"Bearer {token}"},
                json={"question": question, "conversation_id": conversation_id},
            )
            response.raise_for_status()
            return response.json()
