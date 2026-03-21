import logging
from datetime import UTC, datetime

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
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_verified_email
from app.config import settings
from app.db import SessionLocal, get_db
from app.messenger.client import (
    MessengerClientError,
    MetaGraphMessengerClient,
    NoopMessengerClient,
    dispatch_outgoing_message,
)
from app.messenger.constants import (
    ERROR_CODE_MESSENGER_DISABLED,
    ERROR_CODE_MESSENGER_IDENTITY_ALREADY_LINKED,
    ERROR_CODE_MESSENGER_IDENTITY_NOT_FOUND,
    ERROR_CODE_MESSENGER_LINK_TOKEN_INVALID,
    ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
    ERROR_CODE_WEBHOOK_VERIFY_FAILED,
    MESSENGER_PLATFORM,
)
from app.messenger.schemas import (
    MessengerLinkRequest,
    MessengerLinkResponse,
    MessengerWebhookPayload,
    MessengerWebhookProcessResponse,
)
from app.messenger.security import (
    decode_messenger_link_token,
    verify_app_secret_signature,
    verify_webhook_challenge,
)
from app.messenger.service import MessengerEventService
from app.models.messenger_identity import MessengerIdentity
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


def process_webhook_events(*, payload: MessengerWebhookPayload) -> None:
    db = SessionLocal()
    try:
        service = MessengerEventService(db=db)
        client = _get_outbound_client()

        for entry in payload.entry:
            for event in entry.messaging:
                outgoing_messages = service.handle_incoming_event(event=event)
                sender = event.sender.get("id")
                if not sender:
                    continue
                for outgoing in outgoing_messages:
                    try:
                        dispatch_outgoing_message(client=client, psid=sender, outgoing=outgoing)
                    except MessengerClientError:
                        logger.exception(
                            "Messenger outbound delivery failed: sender=%s kind=%s",
                            sender,
                            outgoing.kind,
                        )
                        break
    except Exception:
        logger.exception("Messenger webhook background processing failed")
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
    auth_context: AuthContext = Depends(require_verified_email),
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
    if identity.user_id is not None and identity.user_id != auth_context.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ERROR_CODE_MESSENGER_IDENTITY_ALREADY_LINKED,
                "message": "Messenger identity is already linked to another user",
            },
        )

    identity.user_id = auth_context.user_id
    identity.status = "linked"
    identity.is_active = True
    identity.linked_at = identity.linked_at or datetime.now(UTC)
    db.add(identity)
    db.commit()
    db.refresh(identity)
    return MessengerLinkResponse(
        status="linked",
        user_id=str(auth_context.user_id),
        psid=identity.psid,
        page_id=identity.page_id,
    )


@router.post("/webhook", response_model=MessengerWebhookProcessResponse)
async def receive_webhook(
    payload: MessengerWebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> MessengerWebhookProcessResponse:
    _ensure_messenger_enabled()

    if settings.messenger_verify_signature:
        body = await request.body()
        valid_signature = verify_app_secret_signature(
            body=body,
            signature_header=x_hub_signature_256,
            app_secret=settings.meta_app_secret,
        )
        if not valid_signature:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
                    "message": "Invalid webhook signature",
                },
            )

    processed = sum(len(entry.messaging) for entry in payload.entry)
    background_tasks.add_task(process_webhook_events, payload=payload.model_copy(deep=True))

    return MessengerWebhookProcessResponse(status="accepted", processed=processed)
