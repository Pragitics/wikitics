import base64
import hashlib
import hmac
import json
import os
import time


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


def create_access_token(user_id: str, secret_key: str, ttl_seconds: int) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + ttl_seconds}
    encoded_payload = _b64(payload)
    signature = hmac.new(secret_key.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{encoded_payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def decode_access_token(token: str, secret_key: str) -> str | None:
    try:
        encoded_payload, encoded_signature = token.split(".")
        expected_signature = hmac.new(secret_key.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
        actual_signature = _b64decode(encoded_signature)
        if not hmac.compare_digest(actual_signature, expected_signature):
            return None
        payload = json.loads(_b64decode(encoded_payload))
        if int(payload["exp"]) < int(time.time()):
            return None
        return str(payload["sub"])
    except Exception:
        return None


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8")).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
