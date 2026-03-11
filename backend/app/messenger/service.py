from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.messenger.constants import (
    DEFAULT_UNLINKED_REPLY,
    DEFAULT_UNSUPPORTED_EVENT_REPLY,
    EVENT_TYPE_MESSAGE,
    EVENT_TYPE_POSTBACK,
    EVENT_TYPE_QUICK_REPLY,
    EVENT_TYPE_UNSUPPORTED,
    IDENTITY_STATUS_LINKED,
    IDENTITY_STATUS_UNLINKED,
    MESSENGER_PLATFORM,
)
from app.messenger.schemas import (
    MessengerIncomingCommand,
    MessengerOutgoingMessage,
    MessengerWebhookMessagingEvent,
)
from app.models.messenger_identity import MessengerIdentity


class MessengerEventService:
    def __init__(self, *, db: Session) -> None:
        self._db = db

    def handle_incoming_event(
        self,
        *,
        event: MessengerWebhookMessagingEvent,
    ) -> list[MessengerOutgoingMessage]:
        command = self._to_command(event)
        identity = self.resolve_or_create_identity(psid=command.psid, page_id=command.page_id)
        identity.last_interacted_at = datetime.now(UTC)
        self._db.add(identity)
        self._db.commit()

        if command.event_type == EVENT_TYPE_MESSAGE:
            return self.handle_text_message(command=command, identity=identity)
        if command.event_type == EVENT_TYPE_QUICK_REPLY:
            return self.handle_quick_reply(command=command, identity=identity)
        if command.event_type == EVENT_TYPE_POSTBACK:
            return self.handle_postback(command=command, identity=identity)
        return self.build_outgoing_messages(command=command, identity=identity)

    def handle_text_message(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        _ = command
        if self.maybe_resolve_internal_user(identity=identity) is None:
            return [MessengerOutgoingMessage(kind="text", text=DEFAULT_UNLINKED_REPLY)]
        return [
            MessengerOutgoingMessage(
                kind="text",
                text="已收到你的問題，未來將在此接上既有 ask domain service。",
            )
        ]

    def handle_quick_reply(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        if self.maybe_resolve_internal_user(identity=identity) is None:
            return [MessengerOutgoingMessage(kind="text", text=DEFAULT_UNLINKED_REPLY)]
        payload = command.quick_reply_payload or ""
        return [MessengerOutgoingMessage(kind="text", text=f"已收到 quick reply: {payload}")]

    def handle_postback(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        if self.maybe_resolve_internal_user(identity=identity) is None:
            return [MessengerOutgoingMessage(kind="text", text=DEFAULT_UNLINKED_REPLY)]
        payload = command.postback_payload or ""
        return [MessengerOutgoingMessage(kind="text", text=f"已收到 postback: {payload}")]

    def build_outgoing_messages(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        _ = (command, identity)
        return [MessengerOutgoingMessage(kind="text", text=DEFAULT_UNSUPPORTED_EVENT_REPLY)]

    def maybe_resolve_internal_user(self, *, identity: MessengerIdentity):
        if identity.status == IDENTITY_STATUS_LINKED and identity.user_id is not None:
            return identity.user_id
        return None

    def resolve_or_create_identity(self, *, psid: str, page_id: str | None) -> MessengerIdentity:
        normalized_page_id = (page_id or "").strip()
        identity = self._db.scalar(
            select(MessengerIdentity).where(
                MessengerIdentity.platform == MESSENGER_PLATFORM,
                MessengerIdentity.psid == psid,
                MessengerIdentity.page_id == normalized_page_id,
            )
        )
        if identity is not None:
            if not identity.is_active:
                identity.is_active = True
            return identity

        identity = MessengerIdentity(
            platform=MESSENGER_PLATFORM,
            psid=psid,
            page_id=normalized_page_id,
            status=IDENTITY_STATUS_UNLINKED,
            is_active=True,
            last_interacted_at=datetime.now(UTC),
        )
        self._db.add(identity)
        self._db.flush()
        return identity

    def _to_command(self, event: MessengerWebhookMessagingEvent) -> MessengerIncomingCommand:
        sender_id = event.sender.get("id", "").strip()
        page_id = None
        if event.recipient is not None:
            page_id = event.recipient.get("id")

        occurred_at = None
        if event.timestamp is not None:
            occurred_at = datetime.fromtimestamp(event.timestamp / 1000, tz=UTC)

        if event.message is not None:
            quick_reply_payload = None
            if event.message.quick_reply:
                quick_reply_payload = event.message.quick_reply.get("payload")
            event_type = EVENT_TYPE_QUICK_REPLY if quick_reply_payload else EVENT_TYPE_MESSAGE
            return MessengerIncomingCommand(
                event_type=event_type,
                psid=sender_id,
                page_id=page_id,
                text=event.message.text,
                quick_reply_payload=quick_reply_payload,
                occurred_at=occurred_at,
            )

        if event.postback is not None:
            return MessengerIncomingCommand(
                event_type=EVENT_TYPE_POSTBACK,
                psid=sender_id,
                page_id=page_id,
                postback_payload=event.postback.payload,
                occurred_at=occurred_at,
            )

        return MessengerIncomingCommand(
            event_type=EVENT_TYPE_UNSUPPORTED,
            psid=sender_id,
            page_id=page_id,
            occurred_at=occurred_at,
        )
