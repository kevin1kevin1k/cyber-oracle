from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessengerWebhookVerifyQuery(BaseModel):
    mode: str = Field(alias="hub.mode")
    verify_token: str = Field(alias="hub.verify_token")
    challenge: str = Field(alias="hub.challenge")

    model_config = ConfigDict(populate_by_name=True)


class MessengerWebhookMessagePayload(BaseModel):
    text: str | None = None
    mid: str | None = None
    quick_reply: dict[str, str] | None = None


class MessengerWebhookPostbackPayload(BaseModel):
    payload: str | None = None
    title: str | None = None


class MessengerWebhookMessagingEvent(BaseModel):
    sender: dict[str, str]
    recipient: dict[str, str] | None = None
    timestamp: int | None = None
    message: MessengerWebhookMessagePayload | None = None
    postback: MessengerWebhookPostbackPayload | None = None


class MessengerWebhookEntry(BaseModel):
    id: str | None = None
    time: int | None = None
    messaging: list[MessengerWebhookMessagingEvent] = Field(default_factory=list)


class MessengerWebhookPayload(BaseModel):
    object: str | None = None
    entry: list[MessengerWebhookEntry] = Field(default_factory=list)


class MessengerIncomingCommand(BaseModel):
    event_type: Literal["message", "quick_reply", "postback", "unsupported"]
    psid: str
    page_id: str | None
    text: str | None = None
    message_mid: str | None = None
    postback_payload: str | None = None
    quick_reply_payload: str | None = None
    occurred_at: datetime | None = None


class MessengerQuickReplyOption(BaseModel):
    title: str
    payload: str


class MessengerOutgoingMessage(BaseModel):
    kind: Literal["text", "quick_replies", "button_template"]
    text: str
    quick_replies: list[MessengerQuickReplyOption] = Field(default_factory=list)
    buttons: list[dict[str, str]] = Field(default_factory=list)


class MessengerWebhookProcessResponse(BaseModel):
    status: Literal["accepted"]
    processed: int


class QueuedMessengerWebhookEvent(BaseModel):
    receipt_id: UUID
    event: MessengerWebhookMessagingEvent


class MessengerVerifyResult(BaseModel):
    ok: bool
    challenge: str | None = None


class MessengerLinkRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=2048)


class MessengerLinkResponse(BaseModel):
    status: Literal["linked"]
    link_status: Literal["linked_new", "session_restored"]
    user_id: str
    psid: str
    page_id: str
    access_token: str
    token_type: Literal["bearer"]
