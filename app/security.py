import hmac
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# ---------- password hashing ----------

BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except ValueError:
        return False


# ---------- JWT ----------

JWT_ALGORITHM = "HS256"


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


# ---------- signed download links ----------


def generate_stored_name() -> str:
    return uuid.uuid4().hex


def _signing_payload(file_id: int, expires_at: int) -> bytes:
    return f"{file_id}:{expires_at}".encode("utf-8")


def sign_file_access(file_id: int, ttl_seconds: int) -> tuple[int, str]:
    """Return (expires_at_unix, signature) for a file download link."""
    expires_at = int(
        (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp()
    )
    return expires_at, compute_signature(file_id, expires_at)


def compute_signature(file_id: int, expires_at: int) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        _signing_payload(file_id, expires_at),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(file_id: int, expires_at: int, signature: str) -> bool:
    expected = compute_signature(file_id, expires_at)
    return hmac.compare_digest(expected, signature)


def is_expired(expires_at: int) -> bool:
    return int(datetime.now(timezone.utc).timestamp()) >= expires_at
