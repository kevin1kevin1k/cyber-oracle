from datetime import UTC, datetime
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_authenticated, require_verified_email
from app.config import settings
from app.db import get_db
from app.models.session_record import SessionRecord
from app.models.user import User
from app.schemas import (
    ApiErrorDetail,
    AskRequest,
    AskResponse,
    ErrorResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LayerPercentage,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.security import (
    create_access_token,
    generate_password_reset_token,
    generate_verification_token,
    hash_password,
    password_reset_token_expiry,
    verification_token_expiry,
    verify_password,
)

app = FastAPI(title="ELIN Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/auth/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    responses={409: {"model": ApiErrorDetail}},
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    token = generate_verification_token()
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        email_verified=False,
        verify_token=token,
        verify_token_expires_at=verification_token_expiry(),
        channel=payload.channel or "email",
        channel_user_id=payload.channel_user_id,
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_ALREADY_EXISTS", "message": "Email already exists"},
        ) from exc
    db.refresh(user)

    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        verification_token=token,
    )


@app.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    responses={401: {"model": ApiErrorDetail}},
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    password_valid = False
    if user is not None:
        try:
            password_valid = verify_password(payload.password, user.password_hash)
        except Exception:
            password_valid = False

    if user is None or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )

    access_token = create_access_token(
        subject=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_exp_minutes,
    )
    claims = jwt.decode(access_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    jti = claims.get("jti")
    exp = claims.get("exp")
    iat = claims.get("iat")
    if not isinstance(jti, str) or not isinstance(exp, int) or not isinstance(iat, int):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "TOKEN_GENERATION_FAILED",
                "message": "Unable to generate access token",
            },
        )
    session_record = SessionRecord(
        user_id=user.id,
        jti=jti,
        issued_at=datetime.fromtimestamp(iat, tz=UTC),
        expires_at=datetime.fromtimestamp(exp, tz=UTC),
    )
    db.add(session_record)
    db.commit()

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        email_verified=user.email_verified,
    )


@app.post(
    "/api/v1/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> None:
    session_record = db.scalar(
        select(SessionRecord).where(
            SessionRecord.jti == auth_context.jti,
            SessionRecord.user_id == auth_context.user_id,
        )
    )
    if session_record is not None and session_record.revoked_at is None:
        session_record.revoked_at = datetime.now(UTC)
        db.add(session_record)
        db.commit()


@app.post(
    "/api/v1/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ForgotPasswordResponse,
)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    reset_token: str | None = None
    if user is not None:
        reset_token = generate_password_reset_token()
        user.password_reset_token = reset_token
        user.password_reset_token_expires_at = password_reset_token_expiry()
        db.add(user)
        db.commit()

    if settings.app_env in {"dev", "test"}:
        return ForgotPasswordResponse(status="accepted", reset_token=reset_token)
    return ForgotPasswordResponse(status="accepted")


@app.post(
    "/api/v1/auth/reset-password",
    response_model=ResetPasswordResponse,
    responses={400: {"model": ApiErrorDetail}},
)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> ResetPasswordResponse:
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.password_reset_token == payload.token))
    if (
        user is None
        or user.password_reset_token_expires_at is None
        or user.password_reset_token_expires_at < now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OR_EXPIRED_TOKEN", "message": "Invalid or expired token"},
        )

    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    db.add(user)
    db.commit()

    return ResetPasswordResponse(status="password_reset")


@app.post(
    "/api/v1/auth/verify-email",
    response_model=VerifyEmailResponse,
    responses={400: {"model": ApiErrorDetail}},
)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> VerifyEmailResponse:
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.verify_token == payload.token))

    if user is None or user.verify_token_expires_at is None or user.verify_token_expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OR_EXPIRED_TOKEN", "message": "Invalid or expired token"},
        )

    user.email_verified = True
    user.verify_token = None
    user.verify_token_expires_at = None
    db.add(user)
    db.commit()

    return VerifyEmailResponse(status="verified")


@app.post(
    "/api/v1/ask",
    response_model=AskResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
def ask(payload: AskRequest, _: AuthContext = Depends(require_verified_email)) -> AskResponse:
    return AskResponse(
        answer=f"（Mock）已收到你的問題：{payload.question}。目前為開發環境回覆。",
        source="mock",
        layer_percentages=[
            LayerPercentage(label="主層", pct=70),
            LayerPercentage(label="輔層", pct=20),
            LayerPercentage(label="參照層", pct=10),
        ],
        request_id=str(uuid4()),
    )
