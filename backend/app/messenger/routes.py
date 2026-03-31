import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import issue_user_session
from app.config import settings
from app.db import SessionLocal, get_db
from app.launch import issue_public_launch_grant_if_needed
from app.messenger.client import (
    MessengerClientError,
    MetaGraphMessengerClient,
    NoopMessengerClient,
    dispatch_outgoing_message,
)
from app.messenger.constants import (
    ERROR_CODE_MESSENGER_DISABLED,
    ERROR_CODE_MESSENGER_IDENTITY_NOT_FOUND,
    ERROR_CODE_MESSENGER_LINK_TOKEN_INVALID,
    ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
    ERROR_CODE_WEBHOOK_VERIFY_FAILED,
    MESSENGER_PLATFORM,
)
from app.messenger.schemas import (
    MessengerLinkRequest,
    MessengerLinkResponse,
    MessengerOutgoingMessage,
    MessengerWebhookMessagingEvent,
    MessengerWebhookPayload,
    MessengerWebhookProcessResponse,
    QueuedMessengerWebhookEvent,
)
from app.messenger.security import (
    decode_messenger_link_token,
    verify_app_secret_signature,
    verify_webhook_challenge,
)
from app.messenger.service import (
    MessengerEventService,
    build_linked_new_credit_message,
)
from app.models.messenger_identity import MessengerIdentity
from app.models.messenger_webhook_receipt import MessengerWebhookReceipt
from app.models.user import User
from app.rate_limit import RateLimitRule, enforce_rate_limit

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_messenger_enabled() -> None:
    if not settings.messenger_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ERROR_CODE_MESSENGER_DISABLED,
                "message": "Messenger webhook is disabled",
            },
        )


def _get_outbound_client():
    if settings.messenger_outbound_mode == "meta_graph":
        if not settings.meta_page_access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "MESSENGER_OUTBOUND_NOT_CONFIGURED",
                    "message": "META_PAGE_ACCESS_TOKEN is required for meta_graph mode",
                },
            )
        return MetaGraphMessengerClient(page_access_token=settings.meta_page_access_token)
    return NoopMessengerClient()


def _emit_processing_feedback(*, client, psid: str) -> None:
    for action_name, sender_action in (
        ("mark_seen", client.mark_seen),
        ("typing_on", client.typing_on),
    ):
        try:
            sender_action(psid=psid)
        except MessengerClientError:
            logger.warning(
                "Messenger sender_action failed: psid=%s action=%s",
                psid,
                action_name,
                exc_info=True,
            )


def _stop_processing_feedback(*, client, psid: str) -> None:
    try:
        client.typing_off(psid=psid)
    except MessengerClientError:
        logger.warning(
            "Messenger sender_action failed: psid=%s action=typing_off",
            psid,
            exc_info=True,
        )


def _maybe_send_new_link_credit_message(*, psid: str) -> None:
    if settings.launch_credit_grant_amount <= 0:
        return
    try:
        client = _get_outbound_client()
        dispatch_outgoing_message(
            client=client,
            psid=psid,
            outgoing=MessengerOutgoingMessage(
                kind="text",
                text=build_linked_new_credit_message(),
            ),
        )
    except (HTTPException, MessengerClientError):
        logger.warning(
            "Messenger new-link intro message failed: psid=%s",
            psid,
            exc_info=True,
        )


def _compute_body_sha256(*, body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _current_timestamp() -> datetime:
    return datetime.now(UTC)


def _truncate_payload_summary(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:255]


def _event_type_for_receipt(*, event: MessengerWebhookMessagingEvent) -> str:
    if event.message is not None:
        has_quick_reply = bool(
            event.message.quick_reply and event.message.quick_reply.get("payload")
        )
        return "quick_reply" if has_quick_reply else "message"
    if event.postback is not None:
        return "postback"
    return "unsupported"


def _event_occurred_at(*, event: MessengerWebhookMessagingEvent) -> datetime | None:
    if event.timestamp is None:
        return None
    return datetime.fromtimestamp(event.timestamp / 1000, tz=UTC)


def _canonical_event_json(*, event: MessengerWebhookMessagingEvent) -> str:
    payload = event.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _payload_summary_for_event(
    *,
    event: MessengerWebhookMessagingEvent,
    event_type: str,
) -> str | None:
    if (
        event_type == "quick_reply"
        and event.message is not None
        and event.message.quick_reply is not None
    ):
        return _truncate_payload_summary(event.message.quick_reply.get("payload"))
    if event_type == "postback" and event.postback is not None:
        return _truncate_payload_summary(event.postback.payload)
    return None


def _build_delivery_key(*, event: MessengerWebhookMessagingEvent, event_type: str) -> str:
    if event.message is not None and event.message.mid:
        return f"message:{event.message.mid.strip()}"

    sender_id = (event.sender.get("id") or "").strip()
    page_id = (event.recipient or {}).get("id", "").strip()
    timestamp = str(event.timestamp or "")
    if event_type == "postback" and event.postback is not None:
        seed = f"{sender_id}|{page_id}|{event.postback.payload or ''}|{timestamp}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"postback:{digest}"

    canonical_payload = _canonical_event_json(event=event)
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    return f"unsupported:{digest}"


def _build_webhook_receipt(
    *,
    request_id: str,
    body_sha256: str,
    signature_status: str,
    event: MessengerWebhookMessagingEvent,
) -> MessengerWebhookReceipt:
    event_type = _event_type_for_receipt(event=event)
    return MessengerWebhookReceipt(
        request_id=request_id,
        delivery_key=_build_delivery_key(event=event, event_type=event_type),
        body_sha256=body_sha256,
        event_type=event_type,
        psid=(event.sender.get("id") or "").strip() or None,
        page_id=((event.recipient or {}).get("id") or "").strip() or None,
        message_mid=(
            event.message.mid.strip()
            if event.message is not None and event.message.mid
            else None
        ),
        payload_summary=_payload_summary_for_event(event=event, event_type=event_type),
        occurred_at=_event_occurred_at(event=event),
        signature_status=signature_status,
        processing_status="accepted",
    )


def _insert_receipt(
    *,
    db: Session,
    receipt: MessengerWebhookReceipt,
) -> tuple[MessengerWebhookReceipt, bool]:
    db.add(receipt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(MessengerWebhookReceipt).where(
                MessengerWebhookReceipt.delivery_key == receipt.delivery_key
            )
        )
        if existing is None:
            raise
        if existing.processing_status in {"accepted", "processing"}:
            existing.processing_status = "duplicate_ignored"
            existing.processed_at = _current_timestamp()
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing, False
    db.refresh(receipt)
    return receipt, True


def _record_invalid_signature_receipt(
    *,
    db: Session,
    request_id: str,
    body_sha256: str,
) -> MessengerWebhookReceipt:
    receipt = MessengerWebhookReceipt(
        request_id=request_id,
        delivery_key=f"request:{body_sha256}",
        body_sha256=body_sha256,
        event_type="request",
        signature_status="invalid",
        processing_status="failed",
        error_code=ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
        processed_at=_current_timestamp(),
    )
    stored_receipt, _ = _insert_receipt(db=db, receipt=receipt)
    return stored_receipt


def _set_receipt_processing_status(
    *,
    db: Session,
    receipt_id: UUID,
    processing_status: str,
    error_code: str | None = None,
) -> MessengerWebhookReceipt | None:
    receipt = db.get(MessengerWebhookReceipt, receipt_id)
    if receipt is None:
        return None
    receipt.processing_status = processing_status
    receipt.error_code = error_code
    receipt.processed_at = None if processing_status == "processing" else _current_timestamp()
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _error_code_from_exception(exc: Exception) -> str:
    if isinstance(exc, MessengerClientError):
        return "MESSENGER_OUTBOUND_FAILED"
    if isinstance(exc, HTTPException):
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code")
            if isinstance(code, str) and code.strip():
                return code[:64]
        return f"HTTP_{exc.status_code}"
    return "WEBHOOK_PROCESSING_FAILED"


def process_webhook_events(*, queued_events: list[QueuedMessengerWebhookEvent]) -> None:
    db = SessionLocal()
    try:
        service = MessengerEventService(db=db)
        client = _get_outbound_client()

        for queued_event in queued_events:
            receipt = _set_receipt_processing_status(
                db=db,
                receipt_id=queued_event.receipt_id,
                processing_status="processing",
            )
            request_id = receipt.request_id if receipt is not None else "unknown"
            delivery_key = receipt.delivery_key if receipt is not None else "unknown"
            event = queued_event.event

            try:
                command, identity = service.prepare_incoming_event(event=event)
                sender = event.sender.get("id")
                if not sender:
                    _set_receipt_processing_status(
                        db=db,
                        receipt_id=queued_event.receipt_id,
                        processing_status="succeeded",
                    )
                    continue
                should_emit_feedback = service.should_emit_processing_feedback(
                    command=command,
                    identity=identity,
                )
                if should_emit_feedback:
                    _emit_processing_feedback(client=client, psid=sender)
                try:
                    outgoing_messages = service.handle_prepared_command(
                        command=command,
                        identity=identity,
                    )
                finally:
                    if should_emit_feedback:
                        _stop_processing_feedback(client=client, psid=sender)
                for outgoing in outgoing_messages:
                    dispatch_outgoing_message(client=client, psid=sender, outgoing=outgoing)
                _set_receipt_processing_status(
                    db=db,
                    receipt_id=queued_event.receipt_id,
                    processing_status="succeeded",
                )
                logger.info(
                    "Messenger webhook event processed: request_id=%s delivery_key=%s "
                    "psid=%s page_id=%s event_type=%s",
                    request_id,
                    delivery_key,
                    command.psid,
                    command.page_id,
                    command.event_type,
                )
            except Exception as exc:
                error_code = _error_code_from_exception(exc)
                _set_receipt_processing_status(
                    db=db,
                    receipt_id=queued_event.receipt_id,
                    processing_status="failed",
                    error_code=error_code,
                )
                logger.exception(
                    "Messenger webhook event processing failed: request_id=%s "
                    "delivery_key=%s error_code=%s",
                    request_id,
                    delivery_key,
                    error_code,
                )
    finally:
        db.close()


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> Response:
    _ensure_messenger_enabled()

    verify_result = verify_webhook_challenge(
        mode=hub_mode,
        verify_token=hub_verify_token,
        challenge=hub_challenge,
        expected_verify_token=settings.meta_verify_token,
    )
    if not verify_result.ok or verify_result.challenge is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_WEBHOOK_VERIFY_FAILED,
                "message": "Webhook verification failed",
            },
        )
    return Response(content=verify_result.challenge, media_type="text/plain", status_code=200)


@router.post("/link", response_model=MessengerLinkResponse)
def link_identity(
    payload: MessengerLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessengerLinkResponse:
    _ensure_messenger_enabled()
    client_ip = request.headers.get("x-forwarded-for", "")
    if client_ip.strip():
        client_ip = client_ip.split(",")[0].strip()
    elif request.client is not None and request.client.host:
        client_ip = request.client.host
    else:
        client_ip = "unknown"
    enforce_rate_limit(
        rule=RateLimitRule(name="messenger-link", limit=10, window_seconds=900),
        subject=f"ip:{client_ip}",
    )

    claims = decode_messenger_link_token(
        token=payload.token,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ERROR_CODE_MESSENGER_LINK_TOKEN_INVALID,
                "message": "Messenger link token is invalid or expired",
            },
        )

    identity = db.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.platform == MESSENGER_PLATFORM,
            MessengerIdentity.psid == claims.psid,
            MessengerIdentity.page_id == claims.page_id,
        )
    )
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ERROR_CODE_MESSENGER_IDENTITY_NOT_FOUND,
                "message": "Messenger identity not found",
            },
        )
    link_status = "linked_new"
    if identity.user_id is None:
        user = User(
            channel=MESSENGER_PLATFORM,
            channel_user_id=f"{identity.page_id}:{identity.psid}",
        )
        db.add(user)
        db.flush()
        identity.user_id = user.id
        identity.status = "linked"
        identity.is_active = True
        identity.linked_at = identity.linked_at or datetime.now(UTC)
        db.add(identity)
        db.commit()
        db.refresh(identity)
    else:
        link_status = "session_restored"
        identity.status = "linked"
        identity.is_active = True
        identity.linked_at = identity.linked_at or datetime.now(UTC)
        db.add(identity)
        db.commit()
        db.refresh(identity)

    access_token = issue_user_session(db=db, user_id=identity.user_id)
    wallet_balance = issue_public_launch_grant_if_needed(db=db, user_id=identity.user_id)
    logger.info(
        "messenger.link.success user_id=%s psid=%s link_status=%s balance=%s",
        identity.user_id,
        identity.psid,
        link_status,
        wallet_balance,
    )
    if link_status == "linked_new":
        _maybe_send_new_link_credit_message(psid=identity.psid)
    return MessengerLinkResponse(
        status="linked",
        link_status=link_status,
        user_id=str(identity.user_id),
        psid=identity.psid,
        page_id=identity.page_id,
        access_token=access_token,
        token_type="bearer",
    )


@router.post("/webhook", response_model=MessengerWebhookProcessResponse)
async def receive_webhook(
    payload: MessengerWebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
) -> MessengerWebhookProcessResponse:
    _ensure_messenger_enabled()
    request_id = str(uuid4())
    body = await request.body()
    body_sha256 = _compute_body_sha256(body=body)
    signature_status = "skipped"

    if settings.messenger_verify_signature:
        valid_signature = verify_app_secret_signature(
            body=body,
            signature_header=x_hub_signature_256,
            app_secret=settings.meta_app_secret,
        )
        if not valid_signature:
            _record_invalid_signature_receipt(
                db=db,
                request_id=request_id,
                body_sha256=body_sha256,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
                    "message": "Invalid webhook signature",
                },
            )
        signature_status = "valid"

    processed = sum(len(entry.messaging) for entry in payload.entry)
    queued_events: list[QueuedMessengerWebhookEvent] = []
    for entry in payload.entry:
        for event in entry.messaging:
            receipt = _build_webhook_receipt(
                request_id=request_id,
                body_sha256=body_sha256,
                signature_status=signature_status,
                event=event,
            )
            stored_receipt, is_new = _insert_receipt(db=db, receipt=receipt)
            if not is_new:
                logger.info(
                    "Messenger webhook duplicate ignored: request_id=%s delivery_key=%s "
                    "psid=%s page_id=%s event_type=%s",
                    request_id,
                    stored_receipt.delivery_key,
                    stored_receipt.psid,
                    stored_receipt.page_id,
                    stored_receipt.event_type,
                )
                continue
            queued_events.append(
                QueuedMessengerWebhookEvent(
                    receipt_id=stored_receipt.id,
                    event=event.model_copy(deep=True),
                )
            )

    if queued_events:
        background_tasks.add_task(process_webhook_events, queued_events=queued_events)

    return MessengerWebhookProcessResponse(status="accepted", processed=processed)
