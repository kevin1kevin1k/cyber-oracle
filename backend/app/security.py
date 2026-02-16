import secrets
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash


password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def verification_token_expiry(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
