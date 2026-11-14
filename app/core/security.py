"""Password hashing and JWT token helpers."""

from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes
from uuid import uuid4

import jwt

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_SECRET_KEY


PASSWORD_ITERATIONS = 600_000
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 password hash; never store plaintext passwords."""
    salt = token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${b64encode(salt).decode()}${b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = pbkdf2_hmac("sha256", password.encode("utf-8"), b64decode(salt), int(iterations))
        return compare_digest(candidate, b64decode(expected))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, session_version: str = "") -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "jti": uuid4().hex, "exp": expires_at, "session_version": session_version}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object] | None:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        int(payload["sub"])
        if not payload.get("jti") or not payload.get("exp"):
            return None
        return payload
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None
