"""OTP hashing and JWT helpers.

The OTP flow is a *demo* flow (assumption A2): codes are never delivered by SMS.
In DEMO_MODE the code is a fixed, documented reviewer value; otherwise a random
6-digit code is generated (and would need a real SMS provider to be useful).
Either way only a salted HMAC of the code is stored.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def generate_otp() -> str:
    settings = get_settings()
    if settings.demo_mode:
        return settings.demo_otp
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str, salt: str) -> str:
    key = get_settings().jwt_secret_key.encode()
    return hmac.new(key, f"{salt}:{otp}".encode(), hashlib.sha256).hexdigest()


def verify_otp(otp: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(otp, salt), expected_hash)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expires_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(seconds=expires_in)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM), expires_in


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret_key, algorithms=[ALGORITHM])
