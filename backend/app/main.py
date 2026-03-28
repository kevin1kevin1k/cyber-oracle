import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ask_service import execute_ask_for_user, execute_followup_for_user
from app.auth import AuthContext, require_authenticated
from app.config import settings
from app.db import get_db
from app.messenger.profile_sync import maybe_sync_messenger_profile_on_startup
from app.messenger.routes import router as messenger_router
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.order import Order
from app.models.question import Question
from app.models.session_record import SessionRecord
from app.models.user import User
from app.rate_limit import rate_limiter
from app.schemas import (
    ApiErrorDetail,
    AskHistoryDetailNode,
    AskHistoryDetailResponse,
    AskHistoryDetailTransactionItem,
    AskHistoryItem,
    AskHistoryListResponse,
    AskRequest,
    AskResponse,
    CreateOrderRequest,
    CreditBalanceResponse,
    CreditTransactionItem,
    CreditTransactionListResponse,
    ErrorResponse,
    FollowupOption,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LayerPercentage,
    LoginRequest,
    LoginResponse,
    OrderResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SimulatePaidResponse,
    UpdateUserProfileRequest,
    UserProfileResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.user_profile import is_profile_complete, normalize_profile_value
from openai_integration.openai_file_search_lib import OpenAIFileSearchClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    maybe_sync_messenger_profile_on_startup()
    yield


app = FastAPI(title="ELIN Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(messenger_router, prefix="/api/v1/messenger", tags=["messenger"])

logger = logging.getLogger(__name__)

CREDIT_COST_PER_ASK = 1
ORDER_AMOUNT_TWD_BY_PACKAGE_SIZE = {
    1: 168,
    3: 358,
    5: 518,
}
ASK_HISTORY_PREVIEW_MAX_LENGTH = 160
FOLLOWUP_OPTIONS_COUNT = 3


class AskOpenAIConfigError(Exception):
    pass


class AskOpenAIRuntimeError(Exception):
    pass


def _client_ip_from_request(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for.strip():
        return forwarded_for.split(",")[0].strip()
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


def _enforce_ip_rate_limit(
    *,
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
) -> None:
    ip_address = _client_ip_from_request(request)
    rate_limiter.enforce(
        key=f"ip:{scope}:{ip_address}",
        limit=limit,
        window_seconds=window_seconds,
    )


def _enforce_user_rate_limit(
    *,
    user_id: UUID,
    scope: str,
    limit: int,
    window_seconds: int,
) -> None:
    rate_limiter.enforce(
        key=f"user:{scope}:{user_id}",
        limit=limit,
        window_seconds=window_seconds,
    )


def _raise_disabled_auth_flow() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "AUTH_FLOW_DISABLED",
            "message": "Email/password auth has been disabled; start from Messenger instead",
        },
    )


def _generate_answer_from_openai_file_search(question: str) -> tuple[str, str, list[str]]:
    manifest_path = Path(settings.openai_manifest_path).resolve()
    try:
        client = OpenAIFileSearchClient(
            api_key=settings.openai_api_key,
            model=settings.openai_ask_model,
            vector_store_id=settings.vector_store_id,
        )
        if settings.openai_ask_pipeline == "two_stage":
            result = client.run_two_stage_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_ask_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
        else:
            result = client.run_one_stage_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_ask_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
    except ValueError as exc:
        raise AskOpenAIConfigError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - handled as integration boundary
        raise AskOpenAIRuntimeError("OpenAI ask request failed") from exc

    answer_text = (result.response_text or "").strip()
    if not answer_text:
        raise AskOpenAIRuntimeError("OpenAI response is empty")
    source = "rag" if result.top_matches else "openai"
    return answer_text, source, result.followup_options


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


def _to_ask_response(db: Session, question: Question, answer: Answer) -> AskResponse:
    followup_rows = db.scalars(
        select(Followup)
        .where(Followup.question_id == question.id)
        .order_by(Followup.created_at.asc(), Followup.id.asc())
        .limit(FOLLOWUP_OPTIONS_COUNT)
    ).all()
    return AskResponse(
        answer=answer.answer_text,
        source=question.source,
        layer_percentages=[
            LayerPercentage(label="主層", pct=answer.main_pct),
            LayerPercentage(label="輔層", pct=answer.secondary_pct),
            LayerPercentage(label="參照層", pct=answer.reference_pct),
        ],
        request_id=question.request_id,
        followup_options=[
            FollowupOption(id=str(row.id), content=row.content) for row in followup_rows
        ],
    )


def _build_answer_preview(answer_text: str) -> str:
    if len(answer_text) <= ASK_HISTORY_PREVIEW_MAX_LENGTH:
        return answer_text
    return f"{answer_text[:ASK_HISTORY_PREVIEW_MAX_LENGTH]}..."


def _load_user_profile(*, db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )
    return user


def _to_user_profile_response(*, user: User) -> UserProfileResponse:
    return UserProfileResponse(
        full_name=normalize_profile_value(user.full_name),
        mother_name=normalize_profile_value(user.mother_name),
        is_complete=is_profile_complete(user),
    )


def _resolve_root_question_id(
    *,
    db: Session,
    user_id: UUID,
    question_id: UUID,
) -> UUID:
    current_id = question_id
    visited: set[UUID] = set()

    while current_id not in visited:
        visited.add(current_id)
        parent_followup = db.scalar(
            select(Followup)
            .where(
                Followup.user_id == user_id,
                Followup.used_question_id == current_id,
            )
            .order_by(Followup.created_at.asc(), Followup.id.asc())
            .limit(1)
        )
        if parent_followup is None:
            return current_id
        current_id = parent_followup.question_id

    return current_id


def _build_history_detail_node(
    *,
    question: Question,
    answer: Answer,
    charged_map: dict[UUID, int],
    children_map: dict[UUID, list[UUID]],
    qa_map: dict[UUID, tuple[Question, Answer]],
) -> AskHistoryDetailNode:
    child_nodes = [
        _build_history_detail_node(
            question=qa_map[child_id][0],
            answer=qa_map[child_id][1],
            charged_map=charged_map,
            children_map=children_map,
            qa_map=qa_map,
        )
        for child_id in children_map.get(question.id, [])
        if child_id in qa_map
    ]
    return AskHistoryDetailNode(
        question_id=str(question.id),
        question_text=question.question_text,
        answer_text=answer.answer_text,
        source=question.source,
        layer_percentages=[
            LayerPercentage(label="主層", pct=answer.main_pct),
            LayerPercentage(label="輔層", pct=answer.secondary_pct),
            LayerPercentage(label="參照層", pct=answer.reference_pct),
        ],
        charged_credits=charged_map.get(question.id, 0),
        request_id=question.request_id,
        created_at=question.created_at,
        children=child_nodes,
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
    return _to_ask_response(db=db, question=question, answer=answer)


def _ensure_followups_for_question(
    db: Session,
    *,
    question: Question,
    user_id: UUID,
    request_id: str,
    followup_contents: list[str],
) -> None:
    existing = db.scalars(
        select(Followup)
        .where(Followup.question_id == question.id)
        .order_by(Followup.created_at.asc(), Followup.id.asc())
    ).all()
    if len(existing) >= FOLLOWUP_OPTIONS_COUNT:
        return

    used_contents = {row.content for row in existing}
    for content in followup_contents:
        if len(used_contents) >= FOLLOWUP_OPTIONS_COUNT:
            break
        if content in used_contents:
            continue
        db.add(
            Followup(
                question_id=question.id,
                user_id=user_id,
                content=content,
                origin_request_id=request_id,
                status="pending",
            )
        )
        used_contents.add(content)
def _execute_ask(
    *,
    db: Session,
    user_id: UUID,
    question_text: str,
    lang: str,
    mode: str,
    idempotency_key: str,
) -> tuple[AskResponse, UUID]:
    replayed = _find_existing_ask_response(
        db=db,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if replayed is not None:
        existing_question_id = db.scalar(
            select(Question.id).where(
                Question.user_id == user_id,
                Question.idempotency_key == idempotency_key,
                Question.status == "succeeded",
            )
        )
        if existing_question_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "ASK_REPLAY_FAILED", "message": "Unable to replay ask result"},
            )
        return replayed, existing_question_id

    request_id = str(uuid4())

    wallet = db.scalar(
        select(CreditWallet)
        .where(CreditWallet.user_id == user_id)
        .with_for_update()
    )
    if wallet is None:
        wallet = CreditWallet(user_id=user_id, balance=0)
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
            user_id=user_id,
            action="reserve",
            amount=-CREDIT_COST_PER_ASK,
            reason_code="ASK_RESERVED",
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replayed = _find_existing_ask_response(
            db=db,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            existing_question_id = db.scalar(
                select(Question.id).where(
                    Question.user_id == user_id,
                    Question.idempotency_key == idempotency_key,
                    Question.status == "succeeded",
                )
            )
            if existing_question_id is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"code": "ASK_REPLAY_FAILED", "message": "Unable to replay ask result"},
                ) from exc
            return replayed, existing_question_id
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Duplicate request is in progress"},
        ) from exc

    try:
        answer_text, source, followup_contents = _generate_answer_from_openai_file_search(
            question_text
        )
        question = Question(
            user_id=user_id,
            question_text=question_text,
            lang=lang,
            mode=mode,
            status="succeeded",
            source=source,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        db.add(question)
        db.flush()

        answer = Answer(
            question_id=question.id,
            answer_text=answer_text,
            main_pct=70,
            secondary_pct=20,
            reference_pct=10,
        )
        db.add(answer)
        _ensure_followups_for_question(
            db,
            question=question,
            user_id=user_id,
            request_id=request_id,
            followup_contents=followup_contents,
        )
        db.add(
            CreditTransaction(
                user_id=user_id,
                question_id=question.id,
                action="capture",
                amount=-CREDIT_COST_PER_ASK,
                reason_code="ASK_CAPTURED",
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
        )
        db.commit()
    except AskOpenAIConfigError as exc:
        db.rollback()
        _refund_reserved_credit(
            db=db,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "OPENAI_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except AskOpenAIRuntimeError as exc:
        db.rollback()
        _refund_reserved_credit(
            db=db,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "OPENAI_ASK_FAILED", "message": str(exc)},
        ) from exc
    except Exception as exc:
        db.rollback()
        _refund_reserved_credit(
            db=db,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ASK_PROCESSING_FAILED", "message": "Failed to process ask request"},
        ) from exc

    return _to_ask_response(db=db, question=question, answer=answer), question.id


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
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    _ = (payload, request, db)
    _raise_disabled_auth_flow()


@app.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    responses={401: {"model": ApiErrorDetail}},
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    _ = (payload, request, db)
    _raise_disabled_auth_flow()


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
    request: Request,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    _ = (payload, request, db)
    _raise_disabled_auth_flow()


@app.post(
    "/api/v1/auth/reset-password",
    response_model=ResetPasswordResponse,
    responses={400: {"model": ApiErrorDetail}},
)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> ResetPasswordResponse:
    _ = (payload, db)
    _raise_disabled_auth_flow()


@app.post(
    "/api/v1/auth/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResendVerificationResponse,
)
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ResendVerificationResponse:
    _ = (payload, request, db)
    _raise_disabled_auth_flow()


@app.post(
    "/api/v1/auth/verify-email",
    response_model=VerifyEmailResponse,
    responses={400: {"model": ApiErrorDetail}},
)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> VerifyEmailResponse:
    _ = (payload, db)
    _raise_disabled_auth_flow()


@app.get(
    "/api/v1/me/profile",
    response_model=UserProfileResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_my_profile(
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    user = _load_user_profile(db=db, user_id=auth_context.user_id)
    return _to_user_profile_response(user=user)


@app.put(
    "/api/v1/me/profile",
    response_model=UserProfileResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_my_profile(
    payload: UpdateUserProfileRequest,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    user = _load_user_profile(db=db, user_id=auth_context.user_id)
    user.full_name = payload.full_name
    user.mother_name = payload.mother_name
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_user_profile_response(user=user)


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
        return CreditBalanceResponse(
            balance=0,
            updated_at=None,
            payments_enabled=settings.payments_enabled,
        )
    return CreditBalanceResponse(
        balance=wallet.balance,
        updated_at=wallet.updated_at,
        payments_enabled=settings.payments_enabled,
    )


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


@app.get(
    "/api/v1/history/questions",
    response_model=AskHistoryListResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_ask_history(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> AskHistoryListResponse:
    used_child_ids_subquery = (
        select(Followup.used_question_id)
        .where(
            Followup.user_id == auth_context.user_id,
            Followup.used_question_id.is_not(None),
        )
        .scalar_subquery()
    )
    rows = db.execute(
        select(Question, Answer)
        .join(Answer, Answer.question_id == Question.id)
        .where(
            Question.user_id == auth_context.user_id,
            Question.status == "succeeded",
            ~Question.id.in_(used_child_ids_subquery),
        )
        .order_by(Question.created_at.desc(), Question.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    question_ids = [question.id for question, _ in rows]
    charged_map: dict[UUID, int] = {}
    if question_ids:
        capture_rows = db.execute(
            select(CreditTransaction.question_id, func.sum(CreditTransaction.amount))
            .where(
                CreditTransaction.user_id == auth_context.user_id,
                CreditTransaction.action == "capture",
                CreditTransaction.question_id.in_(question_ids),
            )
            .group_by(CreditTransaction.question_id)
        ).all()
        charged_map = {
            question_id: abs(int(total_amount or 0))
            for question_id, total_amount in capture_rows
            if question_id is not None
        }

    total = db.scalar(
        select(func.count(Question.id)).where(
            Question.user_id == auth_context.user_id,
            Question.status == "succeeded",
            ~Question.id.in_(used_child_ids_subquery),
        )
    )

    items = [
        AskHistoryItem(
            question_id=str(question.id),
            question_text=question.question_text,
            answer_preview=_build_answer_preview(answer.answer_text),
            source=question.source,
            charged_credits=charged_map.get(question.id, 0),
            created_at=question.created_at,
        )
        for question, answer in rows
    ]
    return AskHistoryListResponse(items=items, total=total or 0)


@app.get(
    "/api/v1/history/questions/{question_id}",
    response_model=AskHistoryDetailResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ApiErrorDetail}},
)
def get_ask_history_detail(
    question_id: UUID,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> AskHistoryDetailResponse:
    requested_row = db.execute(
        select(Question, Answer)
        .join(Answer, Answer.question_id == Question.id)
        .where(
            Question.id == question_id,
            Question.user_id == auth_context.user_id,
            Question.status == "succeeded",
        )
    ).first()
    if requested_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUESTION_NOT_FOUND", "message": "Question not found"},
        )

    root_question_id = _resolve_root_question_id(
        db=db,
        user_id=auth_context.user_id,
        question_id=requested_row[0].id,
    )
    root_row = db.execute(
        select(Question, Answer)
        .join(Answer, Answer.question_id == Question.id)
        .where(
            Question.id == root_question_id,
            Question.user_id == auth_context.user_id,
            Question.status == "succeeded",
        )
    ).first()
    if root_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUESTION_NOT_FOUND", "message": "Question not found"},
        )

    qa_map: dict[UUID, tuple[Question, Answer]] = {root_row[0].id: root_row}
    children_map: dict[UUID, list[UUID]] = {}
    frontier: list[UUID] = [root_row[0].id]
    visited: set[UUID] = {root_row[0].id}

    while frontier:
        followup_rows = db.scalars(
            select(Followup)
            .where(
                Followup.user_id == auth_context.user_id,
                Followup.question_id.in_(frontier),
                Followup.used_question_id.is_not(None),
            )
            .order_by(Followup.created_at.asc(), Followup.id.asc())
        ).all()
        if not followup_rows:
            break

        next_ids: list[UUID] = []
        for followup in followup_rows:
            child_id = followup.used_question_id
            if child_id is None:
                continue
            parent_id = followup.question_id
            if child_id not in children_map.get(parent_id, []):
                children_map.setdefault(parent_id, []).append(child_id)
            if child_id not in visited:
                visited.add(child_id)
                next_ids.append(child_id)

        if not next_ids:
            break

        child_rows = db.execute(
            select(Question, Answer)
            .join(Answer, Answer.question_id == Question.id)
            .where(
                Question.user_id == auth_context.user_id,
                Question.status == "succeeded",
                Question.id.in_(next_ids),
            )
        ).all()
        for question, answer in child_rows:
            qa_map[question.id] = (question, answer)
        frontier = [question.id for question, _ in child_rows]

    tree_question_ids = list(qa_map.keys())
    capture_rows = db.execute(
        select(CreditTransaction.question_id, func.sum(CreditTransaction.amount))
        .where(
            CreditTransaction.user_id == auth_context.user_id,
            CreditTransaction.action == "capture",
            CreditTransaction.question_id.in_(tree_question_ids),
        )
        .group_by(CreditTransaction.question_id)
    ).all()
    charged_map = {
        question_id: abs(int(total_amount or 0))
        for question_id, total_amount in capture_rows
        if question_id is not None
    }

    tx_rows = db.scalars(
        select(CreditTransaction)
        .where(
            CreditTransaction.user_id == auth_context.user_id,
            CreditTransaction.question_id.in_(tree_question_ids),
            CreditTransaction.action.in_(["capture", "refund"]),
        )
        .order_by(CreditTransaction.created_at.asc(), CreditTransaction.id.asc())
    ).all()
    transactions = [
        AskHistoryDetailTransactionItem(
            id=str(tx.id),
            action=tx.action,  # type: ignore[arg-type]
            amount=tx.amount,
            reason_code=tx.reason_code,
            question_id=str(tx.question_id) if tx.question_id is not None else None,
            request_id=tx.request_id,
            created_at=tx.created_at,
        )
        for tx in tx_rows
    ]

    root_question, root_answer = root_row
    root = _build_history_detail_node(
        question=root_question,
        answer=root_answer,
        charged_map=charged_map,
        children_map=children_map,
        qa_map=qa_map,
    )
    return AskHistoryDetailResponse(root=root, transactions=transactions)


@app.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    responses={
        401: {"model": ApiErrorDetail},
        403: {"model": ApiErrorDetail},
        409: {"model": ApiErrorDetail},
    },
)
def create_order(
    payload: CreateOrderRequest,
    response: Response,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> OrderResponse:
    if not settings.payments_enabled:
        logger.info("billing.create_order.disabled user_id=%s", auth_context.user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PAYMENTS_DISABLED",
                "message": "Payments are not available in this launch",
            },
        )
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
        500: {"model": ApiErrorDetail},
        502: {"model": ApiErrorDetail},
    },
)
def ask(
    payload: AskRequest,
    request: Request,
    auth_context: AuthContext = Depends(require_authenticated),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> AskResponse:
    _enforce_ip_rate_limit(request=request, scope="ask", limit=30, window_seconds=60)
    _enforce_user_rate_limit(
        user_id=auth_context.user_id,
        scope="ask",
        limit=30,
        window_seconds=60,
    )
    normalized_key = (idempotency_key or "").strip()
    if normalized_key and len(normalized_key) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": "Idempotency-Key is too long"},
        )
    if not normalized_key:
        normalized_key = str(uuid4())
    ask_result = execute_ask_for_user(
        db=db,
        user_id=auth_context.user_id,
        question_text=payload.question,
        lang=payload.lang,
        mode=payload.mode,
        idempotency_key=normalized_key,
        credit_cost_per_ask=CREDIT_COST_PER_ASK,
        followup_limit=FOLLOWUP_OPTIONS_COUNT,
        answer_generator=_generate_answer_from_openai_file_search,
    )
    return ask_result.response


@app.post(
    "/api/v1/followups/{followup_id}/ask",
    response_model=AskResponse,
    responses={
        401: {"model": ApiErrorDetail},
        402: {"model": ApiErrorDetail},
        403: {"model": ApiErrorDetail},
        404: {"model": ApiErrorDetail},
        409: {"model": ApiErrorDetail},
        500: {"model": ApiErrorDetail},
    },
)
def ask_followup(
    followup_id: UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> AskResponse:
    _enforce_ip_rate_limit(request=request, scope="ask-followup", limit=30, window_seconds=60)
    _enforce_user_rate_limit(
        user_id=auth_context.user_id,
        scope="ask-followup",
        limit=30,
        window_seconds=60,
    )
    ask_result = execute_followup_for_user(
        db=db,
        user_id=auth_context.user_id,
        followup_id=followup_id,
        credit_cost_per_ask=CREDIT_COST_PER_ASK,
        followup_limit=FOLLOWUP_OPTIONS_COUNT,
        answer_generator=_generate_answer_from_openai_file_search,
    )
    return ask_result.response
