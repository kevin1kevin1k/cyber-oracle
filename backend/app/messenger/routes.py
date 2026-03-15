import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.messenger.client import (
    MessengerClientError,
    MetaGraphMessengerClient,
    NoopMessengerClient,
    dispatch_outgoing_message,
)
from app.messenger.constants import (
    ERROR_CODE_MESSENGER_DISABLED,
    ERROR_CODE_WEBHOOK_SIGNATURE_INVALID,
    ERROR_CODE_WEBHOOK_VERIFY_FAILED,
)
from app.messenger.schemas import MessengerWebhookPayload, MessengerWebhookProcessResponse
from app.messenger.security import verify_app_secret_signature, verify_webhook_challenge
from app.messenger.service import MessengerEventService

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


@router.post("/webhook", response_model=MessengerWebhookProcessResponse)
async def receive_webhook(
    payload: MessengerWebhookPayload,
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
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

    service = MessengerEventService(db=db)
    client = _get_outbound_client()

    processed = 0
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
            processed += 1

    return MessengerWebhookProcessResponse(status="accepted", processed=processed)
