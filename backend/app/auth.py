from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    email_verified: bool


def _decode_jwt_payload(token: str) -> dict:
    try:
        decoded = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except InvalidTokenError as exc:
        raise ValueError("invalid token payload") from exc

    if not isinstance(decoded, dict):
        raise ValueError("invalid token payload type")

    return decoded


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": "Authentication required"},
    )


def _forbidden_email_not_verified() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "EMAIL_NOT_VERIFIED", "message": "Email verification required"},
    )


def require_verified_email(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        payload = _decode_jwt_payload(credentials.credentials)
    except ValueError as exc:
        raise _unauthorized() from exc

    email_verified = payload.get("email_verified")
    if not isinstance(email_verified, bool):
        raise _unauthorized()
    if not email_verified:
        raise _forbidden_email_not_verified()

    return AuthContext(email_verified=email_verified)
