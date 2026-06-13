import base64
import hashlib
import hmac
import json
import time


class LiveKitVoiceAdapter:
    def __init__(self, url: str, api_key: str, api_secret: str) -> None:
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret

    def token_for_room(self, identity: str, room_name: str, ttl_seconds: int = 3600) -> str:
        payload = {
            "iss": self.api_key,
            "sub": identity,
            "room": room_name,
            "exp": int(time.time()) + ttl_seconds,
            "video": {"roomJoin": True, "room": room_name, "canPublish": True, "canSubscribe": True},
        }
        header = {"alg": "HS256", "typ": "JWT"}
        signing_input = ".".join([self._b64(header), self._b64(payload)])
        signature = hmac.new(self.api_secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
        return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"

    def _b64(self, data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8")).rstrip(b"=").decode("ascii")
