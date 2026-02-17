import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(
    *,
    subject: str,
    email: str,
    email_verified: bool,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=expires_minutes)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "email": email,
        "email_verified": email_verified,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def verification_token_expiry(hours: int = 24) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def generate_password_reset_token() -> str:
    return secrets.token_urlsafe(32)


def password_reset_token_expiry(hours: int = 1) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)
