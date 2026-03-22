import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.session_record import SessionRecord
from app.security import create_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user_id: uuid.UUID
    jti: str


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


def _parse_auth_context(payload: dict) -> AuthContext:
    subject = payload.get("sub")
    jti = payload.get("jti")
    if not isinstance(subject, str):
        raise ValueError("invalid subject claim")
    if not isinstance(jti, str) or not jti.strip():
        raise ValueError("invalid jti claim")
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise ValueError("invalid subject uuid") from exc
    return AuthContext(user_id=user_id, jti=jti)


def require_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        payload = _decode_jwt_payload(credentials.credentials)
        auth_context = _parse_auth_context(payload)
    except ValueError as exc:
        raise _unauthorized() from exc

    session_record = db.scalar(select(SessionRecord).where(SessionRecord.jti == auth_context.jti))
    now = datetime.now(UTC)
    if session_record is None:
        raise _unauthorized()
    if session_record.user_id != auth_context.user_id:
        raise _unauthorized()
    if session_record.revoked_at is not None:
        raise _unauthorized()
    if session_record.expires_at <= now:
        raise _unauthorized()

    return auth_context


def require_verified_email(
    auth_context: AuthContext = Depends(require_authenticated),
) -> AuthContext:
    return auth_context


def issue_user_session(
    *,
    db: Session,
    user_id: uuid.UUID,
    email: str | None = None,
) -> str:
    access_token = create_access_token(
        subject=str(user_id),
        email=email,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_exp_minutes,
    )
    payload = _decode_jwt_payload(access_token)
    jti = payload.get("jti")
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(jti, str) or not isinstance(exp, int) or not isinstance(iat, int):
        raise ValueError("invalid access token payload")

    db.add(
        SessionRecord(
            user_id=user_id,
            jti=jti,
            issued_at=datetime.fromtimestamp(iat, tz=UTC),
            expires_at=datetime.fromtimestamp(exp, tz=UTC),
        )
    )
    db.commit()
    return access_token
