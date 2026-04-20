import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.question import Question
from app.models.user import User
from app.schemas import AskResponse, FollowupOption, LayerPercentage
from app.user_profile import build_augmented_question, ensure_profile_complete
from openai_integration.openai_file_search_lib import OpenAIFileSearchClient


class AskOpenAIConfigError(Exception):
    pass


class AskOpenAIRuntimeError(Exception):
    pass


def _is_openai_config_error(exc: Exception) -> bool:
    return isinstance(exc, AskOpenAIConfigError) or exc.__class__.__name__ == "AskOpenAIConfigError"


def _is_openai_runtime_error(exc: Exception) -> bool:
    return isinstance(exc, AskOpenAIRuntimeError) or (
        exc.__class__.__name__ == "AskOpenAIRuntimeError"
    )


@dataclass
class AskExecutionResult:
    response: AskResponse
    question_id: UUID
    replayed: bool = False


@dataclass
class FollowupExecutionResult:
    response: AskResponse
    question_id: UUID
    followup_id: UUID


def _generate_answer_from_openai_file_search(
    question: str,
    reply_mode: str = "structured",
) -> tuple[str, str, list[str]]:
    manifest_path = Path(settings.openai_manifest_path).resolve()
    try:
        client = OpenAIFileSearchClient(
            api_key=settings.openai_api_key,
            model=settings.openai_ask_model,
            vector_store_id=settings.vector_store_id,
        )
        if reply_mode == "free" and settings.openai_ask_pipeline == "two_stage":
            result = client.run_two_stage_free_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_free_ask_system_prompt,
                followup_system_prompt=settings.openai_free_followup_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
        elif reply_mode == "free":
            result = client.run_one_stage_free_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_free_ask_system_prompt,
                followup_system_prompt=settings.openai_free_followup_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
        elif settings.openai_ask_pipeline == "two_stage":
            result = client.run_two_stage_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_ask_system_prompt,
                enable_compression=settings.openai_ask_enable_compression,
                compression_system_prompt=settings.openai_ask_compression_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
        else:
            result = client.run_one_stage_response(
                question=question,
                manifest_path=manifest_path,
                system_prompt=settings.openai_ask_system_prompt,
                enable_compression=settings.openai_ask_enable_compression,
                compression_system_prompt=settings.openai_ask_compression_system_prompt,
                top_k=settings.openai_ask_top_k,
                model=settings.openai_ask_model,
                debug=False,
            )
    except ValueError as exc:
        raise AskOpenAIConfigError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - integration boundary
        raise AskOpenAIRuntimeError("OpenAI ask request failed") from exc

    answer_text = (result.response_text or "").strip()
    if not answer_text:
        raise AskOpenAIRuntimeError("OpenAI response is empty")
    source = "rag" if result.top_matches else "openai"
    return answer_text, source, result.followup_options


def _invoke_answer_generator(
    generator,
    *,
    question: str,
    reply_mode: str,
) -> tuple[str, str, list[str]]:
    try:
        return generator(question, reply_mode=reply_mode)
    except TypeError as exc:
        if "reply_mode" not in str(exc):
            raise
        return generator(question)


FOLLOWUP_SECTION_MARKERS = (
    "如果你願意",
    "你也可以",
    "延伸問題",
    "我可以再幫你看看",
    "可以再幫你看看",
)


def _strip_followup_section_from_answer(answer_text: str, followup_contents: list[str]) -> str:
    trimmed = answer_text.strip()
    normalized_followups = [item.strip() for item in followup_contents if item.strip()]
    if not trimmed or not normalized_followups:
        return trimmed

    marker_positions = [trimmed.rfind(marker) for marker in FOLLOWUP_SECTION_MARKERS]
    marker_positions = [pos for pos in marker_positions if pos != -1]
    if not marker_positions:
        return trimmed

    cut_at = min(marker_positions)
    suffix = trimmed[cut_at:]
    numbered_line_matches = re.findall(r"(?:^|\n)\s*[1-3][、.．)]\s*", suffix)
    if len(numbered_line_matches) < (1 if len(normalized_followups) == 1 else 2):
        return trimmed

    cleaned = trimmed[:cut_at].rstrip()
    cleaned = re.sub(r"[\s\-:：]+$", "", cleaned)
    return cleaned or trimmed


def _to_ask_response(
    db: Session,
    question: Question,
    answer: Answer,
    followup_limit: int,
) -> AskResponse:
    followup_rows = db.scalars(
        select(Followup)
        .where(Followup.question_id == question.id)
        .order_by(Followup.created_at.asc(), Followup.id.asc())
        .limit(followup_limit)
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


def _find_existing_ask_response(
    db: Session,
    user_id: UUID,
    idempotency_key: str,
    followup_limit: int,
) -> AskExecutionResult | None:
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

    return AskExecutionResult(
        response=_to_ask_response(
            db=db,
            question=question,
            answer=answer,
            followup_limit=followup_limit,
        ),
        question_id=question.id,
        replayed=True,
    )


def _ensure_followups_for_question(
    db: Session,
    *,
    question: Question,
    user_id: UUID,
    request_id: str,
    followup_contents: list[str],
    followup_limit: int,
) -> None:
    existing = db.scalars(
        select(Followup)
        .where(Followup.question_id == question.id)
        .order_by(Followup.created_at.asc(), Followup.id.asc())
    ).all()
    if len(existing) >= followup_limit:
        return

    used_contents = {row.content for row in existing}
    for content in followup_contents:
        if len(used_contents) >= followup_limit:
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


def _refund_reserved_credit(
    db: Session,
    *,
    user_id: UUID,
    request_id: str,
    idempotency_key: str,
    credit_cost_per_ask: int,
    question_id: UUID | None = None,
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

    wallet.balance += credit_cost_per_ask
    db.add(wallet)
    db.add(
        CreditTransaction(
            user_id=user_id,
            question_id=question_id,
            action="refund",
            amount=credit_cost_per_ask,
            reason_code="ASK_REFUNDED",
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
    )
    db.commit()


def execute_ask_for_user(
    *,
    db: Session,
    user_id: UUID,
    question_text: str,
    lang: str,
    mode: str,
    idempotency_key: str,
    credit_cost_per_ask: int = 1,
    followup_limit: int = 3,
    answer_generator=None,
) -> AskExecutionResult:
    replayed = _find_existing_ask_response(
        db=db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        followup_limit=followup_limit,
    )
    if replayed is not None:
        return replayed

    request_id = str(uuid4())
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )
    ensure_profile_complete(user)
    generator = answer_generator or _generate_answer_from_openai_file_search
    reply_mode = user.reply_mode or "structured"

    wallet = db.scalar(
        select(CreditWallet)
        .where(CreditWallet.user_id == user_id)
        .with_for_update()
    )
    if wallet is None:
        wallet = CreditWallet(user_id=user_id, balance=0)
        db.add(wallet)
        db.flush()

    if wallet.balance < credit_cost_per_ask:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "INSUFFICIENT_CREDIT", "message": "Insufficient credit balance"},
        )

    wallet.balance -= credit_cost_per_ask
    db.add(wallet)
    db.add(
        CreditTransaction(
            user_id=user_id,
            action="reserve",
            amount=-credit_cost_per_ask,
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
            followup_limit=followup_limit,
        )
        if replayed is not None:
            return replayed
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Duplicate request is in progress"},
        ) from exc

    try:
        generator_question = build_augmented_question(user=user, question_text=question_text)
        answer_text, source, followup_contents = _invoke_answer_generator(
            generator,
            question=generator_question,
            reply_mode=reply_mode,
        )
        answer_text = _strip_followup_section_from_answer(answer_text, followup_contents)
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
            followup_limit=followup_limit,
        )
        db.add(
            CreditTransaction(
                user_id=user_id,
                question_id=question.id,
                action="capture",
                amount=-credit_cost_per_ask,
                reason_code="ASK_CAPTURED",
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _refund_reserved_credit(
            db,
            user_id=user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            credit_cost_per_ask=credit_cost_per_ask,
        )
        if _is_openai_config_error(exc):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "OPENAI_NOT_CONFIGURED", "message": str(exc)},
            ) from exc
        if _is_openai_runtime_error(exc):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "OPENAI_ASK_FAILED", "message": str(exc)},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "ASK_PROCESSING_FAILED", "message": "Failed to process ask request"},
        ) from exc

    return AskExecutionResult(
        response=_to_ask_response(
            db=db,
            question=question,
            answer=answer,
            followup_limit=followup_limit,
        ),
        question_id=question.id,
    )


def execute_followup_for_user(
    *,
    db: Session,
    user_id: UUID,
    followup_id: UUID,
    credit_cost_per_ask: int = 1,
    followup_limit: int = 3,
    answer_generator=None,
) -> FollowupExecutionResult:
    followup = db.scalar(select(Followup).where(Followup.id == followup_id).with_for_update())
    if followup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FOLLOWUP_NOT_FOUND", "message": "Followup not found"},
        )
    if followup.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FOLLOWUP_OWNER_MISMATCH",
                "message": "Followup does not belong to user",
            },
        )
    if followup.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FOLLOWUP_ALREADY_USED", "message": "Followup has already been used"},
        )

    parent_question = db.scalar(select(Question).where(Question.id == followup.question_id))
    if parent_question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PARENT_QUESTION_NOT_FOUND", "message": "Parent question not found"},
        )

    followup.status = "used"
    followup.used_at = datetime.now(UTC)
    db.add(followup)
    db.commit()

    try:
        ask_result = execute_ask_for_user(
            db=db,
            user_id=user_id,
            question_text=followup.content,
            lang=parent_question.lang,
            mode=parent_question.mode,
            idempotency_key=f"followup:{followup.id}",
            credit_cost_per_ask=credit_cost_per_ask,
            followup_limit=followup_limit,
            answer_generator=answer_generator,
        )
    except HTTPException as exc:
        restore = db.scalar(select(Followup).where(Followup.id == followup_id).with_for_update())
        if restore is not None and restore.status == "used" and restore.used_question_id is None:
            restore.status = "pending"
            restore.used_at = None
            db.add(restore)
            db.commit()
        raise exc

    tracked = db.scalar(select(Followup).where(Followup.id == followup_id).with_for_update())
    if tracked is not None:
        tracked.used_question_id = ask_result.question_id
        db.add(tracked)
        db.commit()

    return FollowupExecutionResult(
        response=ask_result.response,
        question_id=ask_result.question_id,
        followup_id=followup_id,
    )
