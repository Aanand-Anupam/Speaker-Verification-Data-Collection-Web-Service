from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def issue_token(participant_id: str, secret: str, lifetime_seconds: int = 60 * 60 * 24 * 30) -> str:
    payload = _b64(json.dumps({"sub": participant_id, "exp": int(time.time()) + lifetime_seconds}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + "." + signature


def read_token(token: str, secret: str) -> str:
    try:
        payload, signature = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected): raise ValueError
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if int(data["exp"]) < int(time.time()): raise ValueError
        return str(data["sub"])
    except Exception as exc: raise ValueError("Participant session expired; enter your name and roll number again.") from exc
