from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_verified_email
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.schemas import (
    ApiErrorDetail,
    AskRequest,
    AskResponse,
    ErrorResponse,
    LayerPercentage,
    RegisterRequest,
    RegisterResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.security import generate_verification_token, hash_password, verification_token_expiry

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
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_ALREADY_EXISTS", "message": "Email already exists"},
        )
    db.refresh(user)

    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        verification_token=token,
    )


@app.post(
    "/api/v1/auth/verify-email",
    response_model=VerifyEmailResponse,
    responses={400: {"model": ApiErrorDetail}},
)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> VerifyEmailResponse:
    now = datetime.now(timezone.utc)
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
