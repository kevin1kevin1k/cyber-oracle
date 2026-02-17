from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_authenticated, require_verified_email
from app.config import settings
from app.db import get_db
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.order import Order
from app.models.question import Question
from app.models.session_record import SessionRecord
from app.models.user import User
from app.schemas import (
    ApiErrorDetail,
    AskRequest,
    AskResponse,
    CreateOrderRequest,
    CreditBalanceResponse,
    CreditTransactionItem,
    CreditTransactionListResponse,
    ErrorResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LayerPercentage,
    LoginRequest,
    LoginResponse,
    OrderResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SimulatePaidResponse,
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

CREDIT_COST_PER_ASK = 1
ORDER_AMOUNT_TWD_BY_PACKAGE_SIZE = {
    1: 168,
    3: 358,
    5: 518,
}


def _build_mock_answer_text(question: str) -> str:
    return f"（Mock）已收到你的問題：{question}。目前為開發環境回覆。"


def _to_order_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=str(order.id),
        user_id=str(order.user_id),
        package_size=order.package_size,
        amount_twd=order.amount_twd,
        status=order.status,
        idempotency_key=order.idempotency_key,
        created_at=order.created_at,
        paid_at=order.paid_at,
    )


def _to_ask_response(question: Question, answer: Answer) -> AskResponse:
    return AskResponse(
        answer=answer.answer_text,
        source=question.source,
        layer_percentages=[
            LayerPercentage(label="主層", pct=answer.main_pct),
            LayerPercentage(label="輔層", pct=answer.secondary_pct),
            LayerPercentage(label="參照層", pct=answer.reference_pct),
        ],
        request_id=question.request_id,
    )


def _find_existing_ask_response(
    db: Session,
    user_id,
    idempotency_key: str,
) -> AskResponse | None:
    question = db.scalar(
        select(Question).where(
            Question.user_id == user_id,
            Question.idempotency_key == idempotency_key,
            Question.status == "succeeded",
        )
    )
    if question is None:
        return None

    answer = db.scalar(select(Answer).where(Answer.question_id == question.id))
    if answer is None:
        return None
    return _to_ask_response(question, answer)


def _refund_reserved_credit(
    db: Session,
    user_id,
    request_id: str,
    idempotency_key: str,
    question_id=None,
) -> None:
    refund_exists = db.scalar(
        select(CreditTransaction.id).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.action == "refund",
            CreditTransaction.idempotency_key == idempotency_key,
        )
    )
    if refund_exists is not None:
        db.rollback()
        return

    wallet = db.scalar(
        select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
    )
    if wallet is None:
        wallet = CreditWallet(user_id=user_id, balance=0)
        db.add(wallet)
        db.flush()
    wallet.balance += CREDIT_COST_PER_ASK
    db.add(wallet)
    db.add(
        CreditTransaction(
            user_id=user_id,
            question_id=question_id,
            action="refund",
            amount=CREDIT_COST_PER_ASK,
            reason_code="ASK_REFUNDED",
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
    )
    db.commit()


def _get_or_create_wallet_for_update(db: Session, user_id: UUID) -> CreditWallet:
    db.execute(
        pg_insert(CreditWallet)
        .values(user_id=user_id, balance=0)
        .on_conflict_do_nothing(index_elements=[CreditWallet.user_id])
    )
    wallet = db.scalar(
        select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "WALLET_NOT_AVAILABLE", "message": "Wallet is not available"},
        )
    return wallet


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


@app.get(
    "/api/v1/credits/balance",
    response_model=CreditBalanceResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_credits_balance(
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> CreditBalanceResponse:
    wallet = db.scalar(select(CreditWallet).where(CreditWallet.user_id == auth_context.user_id))
    if wallet is None:
        return CreditBalanceResponse(balance=0, updated_at=None)
    return CreditBalanceResponse(balance=wallet.balance, updated_at=wallet.updated_at)


@app.get(
    "/api/v1/credits/transactions",
    response_model=CreditTransactionListResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_credit_transactions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> CreditTransactionListResponse:
    transactions = db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == auth_context.user_id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    total = db.scalar(
        select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == auth_context.user_id
        )
    )

    items = [
        CreditTransactionItem(
            id=str(tx.id),
            action=tx.action,
            amount=tx.amount,
            reason_code=tx.reason_code,
            request_id=tx.request_id,
            question_id=str(tx.question_id) if tx.question_id is not None else None,
            order_id=str(tx.order_id) if tx.order_id is not None else None,
            created_at=tx.created_at,
        )
        for tx in transactions
    ]
    return CreditTransactionListResponse(items=items, total=total or 0)


@app.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    responses={401: {"model": ApiErrorDetail}, 409: {"model": ApiErrorDetail}},
)
def create_order(
    payload: CreateOrderRequest,
    response: Response,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> OrderResponse:
    existing = db.scalar(
        select(Order).where(
            Order.user_id == auth_context.user_id,
            Order.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _to_order_response(existing)

    order = Order(
        user_id=auth_context.user_id,
        package_size=payload.package_size,
        amount_twd=ORDER_AMOUNT_TWD_BY_PACKAGE_SIZE[payload.package_size],
        status="pending",
        idempotency_key=payload.idempotency_key,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(Order).where(
                Order.user_id == auth_context.user_id,
                Order.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return _to_order_response(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ORDER_IDEMPOTENCY_CONFLICT",
                "message": "Conflicting duplicate order request",
            },
        ) from exc

    db.refresh(order)
    response.status_code = status.HTTP_201_CREATED
    return _to_order_response(order)


@app.post(
    "/api/v1/orders/{order_id}/simulate-paid",
    response_model=SimulatePaidResponse,
    responses={
        401: {"model": ApiErrorDetail},
        403: {"model": ApiErrorDetail},
        404: {"model": ApiErrorDetail},
        409: {"model": ApiErrorDetail},
    },
)
def simulate_order_paid(
    order_id: UUID,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> SimulatePaidResponse:
    if settings.app_env == "prod":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_IN_PRODUCTION",
                "message": "simulate-paid is disabled in production",
            },
        )

    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.user_id == auth_context.user_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
        )

    wallet = _get_or_create_wallet_for_update(db=db, user_id=auth_context.user_id)

    if order.status == "paid":
        return SimulatePaidResponse(order=_to_order_response(order), wallet_balance=wallet.balance)

    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ORDER_STATUS_INVALID_FOR_PAYMENT",
                "message": "Only pending orders can be marked as paid",
            },
        )

    request_id = str(uuid4())
    tx_idempotency_key = f"order:{order.id}:purchase"
    existing_purchase = db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.user_id == auth_context.user_id,
            CreditTransaction.action == "purchase",
            CreditTransaction.idempotency_key == tx_idempotency_key,
        )
    )
    if existing_purchase is None:
        wallet.balance += order.package_size
        db.add(wallet)
        db.add(
            CreditTransaction(
                user_id=auth_context.user_id,
                order_id=order.id,
                action="purchase",
                amount=order.package_size,
                reason_code="ORDER_PAID",
                idempotency_key=tx_idempotency_key,
                request_id=request_id,
            )
        )

    order.status = "paid"
    if order.paid_at is None:
        order.paid_at = datetime.now(UTC)
    db.add(order)
    db.commit()
    db.refresh(order)
    db.refresh(wallet)

    return SimulatePaidResponse(order=_to_order_response(order), wallet_balance=wallet.balance)


@app.post(
    "/api/v1/ask",
    response_model=AskResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        402: {"model": ErrorResponse},
    },
)
def ask(
    payload: AskRequest,
    auth_context: AuthContext = Depends(require_verified_email),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> AskResponse:
    normalized_key = (idempotency_key or "").strip()
    if normalized_key and len(normalized_key) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": "Idempotency-Key is too long"},
        )
    if not normalized_key:
        normalized_key = str(uuid4())

    replayed = _find_existing_ask_response(
        db=db,
        user_id=auth_context.user_id,
        idempotency_key=normalized_key,
    )
    if replayed is not None:
        return replayed

    request_id = str(uuid4())

    wallet = db.scalar(
        select(CreditWallet)
        .where(CreditWallet.user_id == auth_context.user_id)
        .with_for_update()
    )
    if wallet is None:
        wallet = CreditWallet(user_id=auth_context.user_id, balance=0)
        db.add(wallet)
        db.flush()

    if wallet.balance < CREDIT_COST_PER_ASK:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "INSUFFICIENT_CREDIT", "message": "Insufficient credit balance"},
        )

    wallet.balance -= CREDIT_COST_PER_ASK
    db.add(wallet)
    db.add(
        CreditTransaction(
            user_id=auth_context.user_id,
            action="reserve",
            amount=-CREDIT_COST_PER_ASK,
            reason_code="ASK_RESERVED",
            idempotency_key=normalized_key,
            request_id=request_id,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replayed = _find_existing_ask_response(
            db=db,
            user_id=auth_context.user_id,
            idempotency_key=normalized_key,
        )
        if replayed is not None:
            return replayed
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Duplicate request is in progress"},
        ) from exc

    try:
        question = Question(
            user_id=auth_context.user_id,
            question_text=payload.question,
            lang=payload.lang,
            mode=payload.mode,
            status="succeeded",
            source="mock",
            request_id=request_id,
            idempotency_key=normalized_key,
        )
        db.add(question)
        db.flush()

        answer = Answer(
            question_id=question.id,
            answer_text=_build_mock_answer_text(payload.question),
            main_pct=70,
            secondary_pct=20,
            reference_pct=10,
        )
        db.add(answer)
        db.add(
            CreditTransaction(
                user_id=auth_context.user_id,
                question_id=question.id,
                action="capture",
                amount=-CREDIT_COST_PER_ASK,
                reason_code="ASK_CAPTURED",
                idempotency_key=normalized_key,
                request_id=request_id,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _refund_reserved_credit(
            db=db,
            user_id=auth_context.user_id,
            request_id=request_id,
            idempotency_key=normalized_key,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ASK_PROCESSING_FAILED", "message": "Failed to process ask request"},
        ) from exc

    return _to_ask_response(question=question, answer=answer)
