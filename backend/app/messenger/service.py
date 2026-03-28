import hashlib
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ask_service import execute_ask_for_user, execute_followup_for_user
from app.config import settings
from app.messenger.constants import (
    DEFAULT_FOLLOWUP_PROMPT_TEXT,
    DEFAULT_MESSENGER_ASK_CONFIG_REPLY,
    DEFAULT_MESSENGER_ASK_FAILED_REPLY,
    DEFAULT_MESSENGER_ASK_UPSTREAM_REPLY,
    DEFAULT_MESSENGER_BALANCE_BUTTON_TITLE,
    DEFAULT_MESSENGER_BALANCE_REPLY,
    DEFAULT_MESSENGER_FOLLOWUP_CONFIG_REPLY,
    DEFAULT_MESSENGER_FOLLOWUP_FAILED_REPLY,
    DEFAULT_MESSENGER_FOLLOWUP_UNAVAILABLE_REPLY,
    DEFAULT_MESSENGER_FOLLOWUP_UPSTREAM_REPLY,
    DEFAULT_MESSENGER_GET_STARTED_BUTTON_TITLE,
    DEFAULT_MESSENGER_GET_STARTED_ONBOARDING_REPLY,
    DEFAULT_MESSENGER_GET_STARTED_REPLY,
    DEFAULT_MESSENGER_GREETING_TEXT,
    DEFAULT_MESSENGER_INVALID_FOLLOWUP_REPLY,
    DEFAULT_MESSENGER_LINK_BUTTON_TITLE,
    DEFAULT_MESSENGER_OPEN_SETTINGS_BUTTON_TITLE,
    DEFAULT_MESSENGER_OPEN_SETTINGS_REPLY,
    DEFAULT_MESSENGER_PAYMENTS_DISABLED_REPLY,
    DEFAULT_MESSENGER_POST_ASK_BALANCE_REPLY,
    DEFAULT_MESSENGER_PROFILE_BUTTON_TITLE,
    DEFAULT_MESSENGER_PROFILE_REPLAY_ASK_BUTTON_TITLE,
    DEFAULT_MESSENGER_PROFILE_REQUIRED_REPLY,
    DEFAULT_MESSENGER_REPLAY_ASK_BUTTON_TITLE,
    DEFAULT_MESSENGER_REPLAY_ASK_UNAVAILABLE_REPLY,
    DEFAULT_MESSENGER_RESHOW_FOLLOWUPS_BUTTON_TITLE,
    DEFAULT_MESSENGER_RESHOW_FOLLOWUPS_UNAVAILABLE_REPLY,
    DEFAULT_MESSENGER_SETTINGS_BUTTON_TITLE,
    DEFAULT_MESSENGER_TOPUP_BUTTON_TITLE,
    DEFAULT_MESSENGER_TOPUP_REPLY,
    DEFAULT_UNLINKED_REPLY,
    DEFAULT_UNSUPPORTED_EVENT_REPLY,
    EVENT_TYPE_MESSAGE,
    EVENT_TYPE_POSTBACK,
    EVENT_TYPE_QUICK_REPLY,
    EVENT_TYPE_UNSUPPORTED,
    GET_STARTED_PAYLOAD,
    IDENTITY_STATUS_LINKED,
    IDENTITY_STATUS_UNLINKED,
    MESSENGER_PLATFORM,
    OPEN_HISTORY_PAYLOAD,
    OPEN_SETTINGS_PAYLOAD,
    OPEN_WALLET_PAYLOAD,
    SHOW_BALANCE_PAYLOAD,
)
from app.messenger.schemas import (
    MessengerIncomingCommand,
    MessengerOutgoingMessage,
    MessengerQuickReplyOption,
    MessengerWebhookMessagingEvent,
)
from app.messenger.security import create_messenger_link_token
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.messenger_identity import MessengerIdentity
from app.models.messenger_pending_ask import MessengerPendingAsk
from app.models.user import User
from app.user_profile import PROFILE_INCOMPLETE_CODE, is_profile_complete

ASK_DEFAULT_LANG = "zh"
ASK_DEFAULT_MODE = "analysis"
ASK_IDEMPOTENCY_PREFIX = "msg"
FOLLOWUP_PAYLOAD_PREFIX = "FOLLOWUP:"
RESHOW_FOLLOWUPS_PAYLOAD_PREFIX = "RESHOW_FOLLOWUPS:"
REPLAY_PENDING_ASK_PAYLOAD_PREFIX = "REPLAY_PENDING_ASK:"
FOLLOWUP_BUTTON_TITLES = ("延伸問題一", "延伸問題二", "延伸問題三")


class MessengerEventService:
    def __init__(self, *, db: Session) -> None:
        self._db = db

    def prepare_incoming_event(
        self,
        *,
        event: MessengerWebhookMessagingEvent,
    ) -> tuple[MessengerIncomingCommand, MessengerIdentity]:
        command = self._to_command(event)
        identity = self.resolve_or_create_identity(psid=command.psid, page_id=command.page_id)
        identity.last_interacted_at = datetime.now(UTC)
        self._db.add(identity)
        self._db.commit()
        return command, identity

    def handle_incoming_event(
        self,
        *,
        event: MessengerWebhookMessagingEvent,
    ) -> list[MessengerOutgoingMessage]:
        command, identity = self.prepare_incoming_event(event=event)
        return self.handle_prepared_command(command=command, identity=identity)

    def handle_prepared_command(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        if command.event_type == EVENT_TYPE_MESSAGE:
            return self.handle_text_message(command=command, identity=identity)
        if command.event_type == EVENT_TYPE_QUICK_REPLY:
            return self.handle_quick_reply(command=command, identity=identity)
        if command.event_type == EVENT_TYPE_POSTBACK:
            return self.handle_postback(command=command, identity=identity)
        return self.build_outgoing_messages(command=command, identity=identity)

    def should_emit_processing_feedback(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> bool:
        user_id = self.maybe_resolve_internal_user(identity=identity)
        if user_id is None or not self._has_complete_profile(user_id=user_id):
            return False

        if command.event_type == EVENT_TYPE_MESSAGE:
            return bool((command.text or "").strip())

        if command.event_type == EVENT_TYPE_QUICK_REPLY:
            followup_id = self._parse_followup_payload(command.quick_reply_payload)
            if followup_id is None:
                return False
            followup = self._db.scalar(select(Followup).where(Followup.id == followup_id))
            return (
                followup is not None
                and followup.user_id == user_id
                and followup.status == "pending"
            )

        if command.event_type == EVENT_TYPE_POSTBACK:
            pending_ask_id = self._parse_replay_pending_ask_payload(command.postback_payload)
            if pending_ask_id is None:
                return False
            pending_ask = self._db.scalar(
                select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask_id)
            )
            return (
                pending_ask is not None
                and pending_ask.user_id == user_id
                and pending_ask.messenger_identity_id == identity.id
                and pending_ask.status == "pending"
            )

        return False

    def handle_text_message(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        user_id = self.maybe_resolve_internal_user(identity=identity)
        if user_id is None:
            return [self.build_linking_message(identity=identity)]
        if not self._has_complete_profile(user_id=user_id):
            question_text = (command.text or "").strip()
            pending_ask_id = None
            if question_text:
                pending_ask = self._create_or_get_pending_ask(
                    identity=identity,
                    user_id=user_id,
                    question_text=question_text,
                    lang=ASK_DEFAULT_LANG,
                    mode=ASK_DEFAULT_MODE,
                    idempotency_key=self._build_event_idempotency_key(command=command),
                )
                pending_ask_id = pending_ask.id
            return [
                self.build_profile_required_message(
                    identity=identity,
                    pending_ask_id=pending_ask_id,
                )
            ]

        question_text = (command.text or "").strip()
        if not question_text:
            return [MessengerOutgoingMessage(kind="text", text=DEFAULT_UNSUPPORTED_EVENT_REPLY)]

        idempotency_key = self._build_event_idempotency_key(command=command)
        try:
            ask_result = execute_ask_for_user(
                db=self._db,
                user_id=user_id,
                question_text=question_text,
                lang=ASK_DEFAULT_LANG,
                mode=ASK_DEFAULT_MODE,
                idempotency_key=idempotency_key,
            )
        except HTTPException as exc:
            if exc.status_code == 402:
                if not settings.payments_enabled:
                    return [self.build_topup_message()]
                pending_ask = self._create_or_get_pending_ask(
                    identity=identity,
                    user_id=user_id,
                    question_text=question_text,
                    lang=ASK_DEFAULT_LANG,
                    mode=ASK_DEFAULT_MODE,
                    idempotency_key=idempotency_key,
                )
                return [self.build_topup_message(identity=identity, pending_ask_id=pending_ask.id)]
            if isinstance(exc.detail, dict) and exc.detail.get("code") == PROFILE_INCOMPLETE_CODE:
                return [self.build_profile_required_message(identity=identity)]
            return [self._build_ask_failure_message(exc=exc)]

        if ask_result.replayed and command.message_mid:
            return []

        return self._build_answer_outgoing_messages(
            user_id=user_id,
            answer_text=ask_result.response.answer,
            followup_options=ask_result.response.followup_options,
        )

    def handle_quick_reply(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        user_id = self.maybe_resolve_internal_user(identity=identity)
        if user_id is None:
            return [self.build_linking_message(identity=identity)]
        if not self._has_complete_profile(user_id=user_id):
            return [self.build_profile_required_message(identity=identity)]

        followup_id = self._parse_followup_payload(command.quick_reply_payload)
        if followup_id is None:
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_INVALID_FOLLOWUP_REPLY,
                )
            ]

        try:
            followup_result = execute_followup_for_user(
                db=self._db,
                user_id=user_id,
                followup_id=followup_id,
            )
        except HTTPException as exc:
            if exc.status_code == 402:
                if not settings.payments_enabled:
                    return [self.build_topup_message()]
                return [self.build_topup_message(identity=identity, followup_id=followup_id)]
            if isinstance(exc.detail, dict) and exc.detail.get("code") == PROFILE_INCOMPLETE_CODE:
                return [self.build_profile_required_message(identity=identity)]
            if exc.status_code in {403, 404, 409}:
                return [
                    MessengerOutgoingMessage(
                        kind="text",
                        text=DEFAULT_MESSENGER_FOLLOWUP_UNAVAILABLE_REPLY,
                    )
                ]
            return [
                self._build_followup_failure_message(exc=exc)
            ]

        return self._build_answer_outgoing_messages(
            user_id=user_id,
            answer_text=followup_result.response.answer,
            followup_options=followup_result.response.followup_options,
        )

    def handle_postback(
        self,
        *,
        command: MessengerIncomingCommand,
        identity: MessengerIdentity,
    ) -> list[MessengerOutgoingMessage]:
        payload = command.postback_payload or ""
        if payload == GET_STARTED_PAYLOAD:
            user_id = self.maybe_resolve_internal_user(identity=identity)
            if user_id is None or not self._has_complete_profile(user_id=user_id):
                return [
                    MessengerOutgoingMessage(
                        kind="button_template",
                        text=DEFAULT_MESSENGER_GET_STARTED_ONBOARDING_REPLY,
                        buttons=[
                            {
                                "type": "web_url",
                                "title": DEFAULT_MESSENGER_GET_STARTED_BUTTON_TITLE,
                                "url": self._build_messenger_link_url(
                                    identity=identity,
                                    next_path="/?from=messenger-get-started",
                                ),
                            }
                        ],
                    )
                ]
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_GET_STARTED_REPLY,
                )
            ]
        if payload == OPEN_SETTINGS_PAYLOAD:
            return [self.build_settings_entry_message(identity=identity)]
        if payload == OPEN_WALLET_PAYLOAD:
            return [self.build_settings_entry_message(identity=identity)]
        if payload == OPEN_HISTORY_PAYLOAD:
            return [self.build_settings_entry_message(identity=identity)]
        if self.maybe_resolve_internal_user(identity=identity) is None:
            return [self.build_linking_message(identity=identity)]
        if payload == SHOW_BALANCE_PAYLOAD:
            return self._build_balance_messages(identity=identity, user_id=identity.user_id)
        reshow_followup_id = self._parse_reshow_followups_payload(payload)
        if reshow_followup_id is not None:
            return self._reshow_followup_messages(
                user_id=identity.user_id,
                followup_id=reshow_followup_id,
            )
        replay_pending_ask_id = self._parse_replay_pending_ask_payload(payload)
        if replay_pending_ask_id is not None:
            return self._replay_pending_ask_messages(
                identity=identity,
                user_id=identity.user_id,
                pending_ask_id=replay_pending_ask_id,
            )
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

    def _build_answer_outgoing_messages(
        self,
        *,
        user_id: UUID,
        answer_text: str,
        followup_options,
    ) -> list[MessengerOutgoingMessage]:
        balance_message = MessengerOutgoingMessage(
            kind="text",
            text=DEFAULT_MESSENGER_POST_ASK_BALANCE_REPLY.format(
                balance=self._get_wallet_balance(user_id=user_id)
            ),
        )
        if not followup_options:
            return [MessengerOutgoingMessage(kind="text", text=answer_text), balance_message]

        followup_lines = self._format_followup_lines(followup_options)
        quick_replies = [
            MessengerQuickReplyOption(
                title=FOLLOWUP_BUTTON_TITLES[index],
                payload=f"{FOLLOWUP_PAYLOAD_PREFIX}{option.id}",
            )
            for index, option in enumerate(followup_options)
        ]
        return [
            MessengerOutgoingMessage(
                kind="quick_replies",
                text=(
                    f"{answer_text}\n\n{DEFAULT_FOLLOWUP_PROMPT_TEXT}\n"
                    + "\n".join(followup_lines)
                ),
                quick_replies=quick_replies,
            ),
            balance_message,
        ]

    def _build_followup_outgoing_messages(self, followup_options) -> list[MessengerOutgoingMessage]:
        if not followup_options:
            return []
        quick_replies = [
            MessengerQuickReplyOption(
                title=FOLLOWUP_BUTTON_TITLES[index],
                payload=f"{FOLLOWUP_PAYLOAD_PREFIX}{option.id}",
            )
            for index, option in enumerate(followup_options)
        ]
        return [
            MessengerOutgoingMessage(
                kind="quick_replies",
                text=f"{DEFAULT_FOLLOWUP_PROMPT_TEXT}\n" + "\n".join(
                    self._format_followup_lines(followup_options)
                ),
                quick_replies=quick_replies,
            )
        ]

    def _format_followup_lines(self, followup_options) -> list[str]:
        return [f"{index + 1}. {option.content}" for index, option in enumerate(followup_options)]

    def _get_wallet_balance(self, *, user_id: UUID) -> int:
        wallet = self._db.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
        return wallet.balance if wallet is not None else 0

    def build_linking_message(self, *, identity: MessengerIdentity) -> MessengerOutgoingMessage:
        return MessengerOutgoingMessage(
            kind="button_template",
            text=DEFAULT_UNLINKED_REPLY,
            buttons=[
                {
                    "type": "web_url",
                    "title": DEFAULT_MESSENGER_LINK_BUTTON_TITLE,
                    "url": self._build_messenger_link_url(identity=identity),
                }
            ],
        )

    def build_settings_entry_message(
        self,
        *,
        identity: MessengerIdentity,
    ) -> MessengerOutgoingMessage:
        user_id = self.maybe_resolve_internal_user(identity=identity)
        next_path: str | None = "/"
        if user_id is None:
            next_path = None
        elif not self._has_complete_profile(user_id=user_id):
            next_path = "/?from=messenger-profile-required"
        return self._build_menu_bridge_message(
            identity=identity,
            next_path=next_path,
            text=DEFAULT_MESSENGER_OPEN_SETTINGS_REPLY,
            button_title=DEFAULT_MESSENGER_OPEN_SETTINGS_BUTTON_TITLE,
        )

    def build_profile_required_message(
        self,
        *,
        identity: MessengerIdentity,
        pending_ask_id: UUID | None = None,
    ) -> MessengerOutgoingMessage:
        buttons: list[dict[str, str]] = [
            {
                    "type": "web_url",
                    "title": DEFAULT_MESSENGER_PROFILE_BUTTON_TITLE,
                    "url": self._build_messenger_link_url(
                        identity=identity,
                        next_path="/?from=messenger-profile-required",
                    ),
                }
            ]
        if pending_ask_id is not None:
            buttons.append(
                {
                    "type": "postback",
                    "title": DEFAULT_MESSENGER_PROFILE_REPLAY_ASK_BUTTON_TITLE,
                    "payload": f"{REPLAY_PENDING_ASK_PAYLOAD_PREFIX}{pending_ask_id}",
                }
            )
        return MessengerOutgoingMessage(
            kind="button_template",
            text=DEFAULT_MESSENGER_PROFILE_REQUIRED_REPLY,
            buttons=buttons,
        )

    def build_topup_message(
        self,
        *,
        identity: MessengerIdentity | None = None,
        followup_id: UUID | None = None,
        pending_ask_id: UUID | None = None,
    ) -> MessengerOutgoingMessage:
        if not settings.payments_enabled:
            return MessengerOutgoingMessage(
                kind="text",
                text=DEFAULT_MESSENGER_PAYMENTS_DISABLED_REPLY,
            )
        topup_url = f"{self._base_web_url()}/wallet?from=messenger-insufficient-credit"
        if identity is not None:
            topup_url = self._build_messenger_link_url(
                identity=identity,
                next_path="/wallet?from=messenger-insufficient-credit",
            )
        buttons: list[dict[str, str]] = [
            {
                "type": "web_url",
                "title": DEFAULT_MESSENGER_TOPUP_BUTTON_TITLE,
                "url": topup_url,
            }
        ]
        if followup_id is not None:
            buttons.append(
                {
                    "type": "postback",
                    "title": DEFAULT_MESSENGER_RESHOW_FOLLOWUPS_BUTTON_TITLE,
                    "payload": f"{RESHOW_FOLLOWUPS_PAYLOAD_PREFIX}{followup_id}",
                }
            )
        elif pending_ask_id is not None:
            buttons.append(
                {
                    "type": "postback",
                    "title": DEFAULT_MESSENGER_REPLAY_ASK_BUTTON_TITLE,
                    "payload": f"{REPLAY_PENDING_ASK_PAYLOAD_PREFIX}{pending_ask_id}",
                }
            )
        return MessengerOutgoingMessage(
            kind="button_template",
            text=DEFAULT_MESSENGER_TOPUP_REPLY,
            buttons=buttons,
        )

    def _build_menu_bridge_message(
        self,
        *,
        identity: MessengerIdentity,
        next_path: str | None,
        text: str,
        button_title: str,
    ) -> MessengerOutgoingMessage:
        return MessengerOutgoingMessage(
            kind="button_template",
            text=text,
            buttons=[
                {
                    "type": "web_url",
                    "title": button_title,
                    "url": self._build_messenger_link_url(identity=identity, next_path=next_path),
                }
            ],
        )

    def _build_balance_messages(
        self,
        *,
        identity: MessengerIdentity,
        user_id,
    ) -> list[MessengerOutgoingMessage]:
        wallet = self._db.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
        balance = wallet.balance if wallet is not None else 0
        if balance <= 0:
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_BALANCE_REPLY.format(balance=balance),
                ),
                self.build_topup_message(identity=identity),
            ]
        return [
            MessengerOutgoingMessage(
                kind="text",
                text=DEFAULT_MESSENGER_BALANCE_REPLY.format(balance=balance),
            )
        ]

    def _reshow_followup_messages(
        self,
        *,
        user_id,
        followup_id: UUID,
    ) -> list[MessengerOutgoingMessage]:
        followup = self._db.scalar(select(Followup).where(Followup.id == followup_id))
        if followup is None or followup.user_id != user_id:
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_RESHOW_FOLLOWUPS_UNAVAILABLE_REPLY,
                )
            ]

        pending_followups = self._db.scalars(
            select(Followup)
            .where(
                Followup.question_id == followup.question_id,
                Followup.user_id == user_id,
                Followup.status == "pending",
            )
            .order_by(Followup.created_at.asc(), Followup.id.asc())
        ).all()
        if not pending_followups:
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_RESHOW_FOLLOWUPS_UNAVAILABLE_REPLY,
                )
            ]

        return self._build_followup_outgoing_messages(pending_followups)

    def _create_or_get_pending_ask(
        self,
        *,
        identity: MessengerIdentity,
        user_id: UUID,
        question_text: str,
        lang: str,
        mode: str,
        idempotency_key: str,
    ) -> MessengerPendingAsk:
        existing_pending_ask = self._db.scalar(
            select(MessengerPendingAsk).where(
                MessengerPendingAsk.user_id == user_id,
                MessengerPendingAsk.idempotency_key == idempotency_key,
            )
        )
        if existing_pending_ask is not None:
            return existing_pending_ask

        pending_ask = MessengerPendingAsk(
            user_id=user_id,
            messenger_identity_id=identity.id,
            question_text=question_text,
            lang=lang,
            mode=mode,
            idempotency_key=idempotency_key,
            status="pending",
        )
        self._db.add(pending_ask)
        self._db.commit()
        self._db.refresh(pending_ask)
        return pending_ask

    def _replay_pending_ask_messages(
        self,
        *,
        identity: MessengerIdentity,
        user_id,
        pending_ask_id: UUID,
    ) -> list[MessengerOutgoingMessage]:
        pending_ask = self._db.scalar(
            select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask_id)
        )
        if (
            pending_ask is None
            or pending_ask.user_id != user_id
            or pending_ask.messenger_identity_id != identity.id
            or pending_ask.status != "pending"
        ):
            return [
                MessengerOutgoingMessage(
                    kind="text",
                    text=DEFAULT_MESSENGER_REPLAY_ASK_UNAVAILABLE_REPLY,
                )
            ]

        try:
            ask_result = execute_ask_for_user(
                db=self._db,
                user_id=user_id,
                question_text=pending_ask.question_text,
                lang=pending_ask.lang,
                mode=pending_ask.mode,
                idempotency_key=f"pending-ask:{pending_ask.id}",
            )
        except HTTPException as exc:
            if exc.status_code == 402:
                return [self.build_topup_message(identity=identity, pending_ask_id=pending_ask.id)]
            if isinstance(exc.detail, dict) and exc.detail.get("code") == PROFILE_INCOMPLETE_CODE:
                return [
                    self.build_profile_required_message(
                        identity=identity,
                        pending_ask_id=pending_ask.id,
                    )
                ]
            return [self._build_ask_failure_message(exc=exc)]

        tracked_pending_ask = self._db.scalar(
            select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
        )
        if tracked_pending_ask is not None and tracked_pending_ask.status == "pending":
            tracked_pending_ask.status = "used"
            tracked_pending_ask.used_question_id = ask_result.question_id
            tracked_pending_ask.used_at = datetime.now(UTC)
            self._db.add(tracked_pending_ask)
            self._db.commit()

        return self._build_answer_outgoing_messages(
            user_id=user_id,
            answer_text=ask_result.response.answer,
            followup_options=ask_result.response.followup_options,
        )

    def _base_web_url(self) -> str:
        return settings.messenger_web_base_url.rstrip("/")

    def _build_messenger_link_url(
        self,
        *,
        identity: MessengerIdentity,
        next_path: str | None = None,
    ) -> str:
        link_token = create_messenger_link_token(
            psid=identity.psid,
            page_id=identity.page_id,
            secret_key=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        query_params = {"token": link_token}
        if next_path:
            query_params["next"] = next_path
        return f"{self._base_web_url()}/messenger/link?{urlencode(query_params)}"

    def _has_complete_profile(self, *, user_id: UUID) -> bool:
        user = self._db.scalar(select(User).where(User.id == user_id))
        return is_profile_complete(user)

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
                message_mid=event.message.mid,
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

    def _build_event_idempotency_key(self, *, command: MessengerIncomingCommand) -> str:
        seed = command.message_mid or ""
        if not seed and command.occurred_at is not None:
            seed = str(int(command.occurred_at.timestamp()))
        if not seed:
            seed = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(f"{command.psid}:{seed}".encode()).hexdigest()[:40]
        return f"{ASK_IDEMPOTENCY_PREFIX}:{digest}"

    def _parse_followup_payload(self, payload: str | None) -> UUID | None:
        if payload is None:
            return None
        normalized = payload.strip()
        if not normalized.startswith(FOLLOWUP_PAYLOAD_PREFIX):
            return None
        raw_followup_id = normalized.removeprefix(FOLLOWUP_PAYLOAD_PREFIX).strip()
        if not raw_followup_id:
            return None
        try:
            return UUID(raw_followup_id)
        except ValueError:
            return None

    def _parse_reshow_followups_payload(self, payload: str | None) -> UUID | None:
        if payload is None:
            return None
        normalized = payload.strip()
        if not normalized.startswith(RESHOW_FOLLOWUPS_PAYLOAD_PREFIX):
            return None
        raw_followup_id = normalized.removeprefix(RESHOW_FOLLOWUPS_PAYLOAD_PREFIX).strip()
        if not raw_followup_id:
            return None
        try:
            return UUID(raw_followup_id)
        except ValueError:
            return None

    def _parse_replay_pending_ask_payload(self, payload: str | None) -> UUID | None:
        if payload is None:
            return None
        normalized = payload.strip()
        if not normalized.startswith(REPLAY_PENDING_ASK_PAYLOAD_PREFIX):
            return None
        raw_pending_ask_id = normalized.removeprefix(REPLAY_PENDING_ASK_PAYLOAD_PREFIX).strip()
        if not raw_pending_ask_id:
            return None
        try:
            return UUID(raw_pending_ask_id)
        except ValueError:
            return None

    def _build_ask_failure_message(self, *, exc: HTTPException) -> MessengerOutgoingMessage:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code")
        if code == "OPENAI_NOT_CONFIGURED":
            return MessengerOutgoingMessage(kind="text", text=DEFAULT_MESSENGER_ASK_CONFIG_REPLY)
        if code == "OPENAI_ASK_FAILED":
            return MessengerOutgoingMessage(kind="text", text=DEFAULT_MESSENGER_ASK_UPSTREAM_REPLY)
        return MessengerOutgoingMessage(kind="text", text=DEFAULT_MESSENGER_ASK_FAILED_REPLY)

    def _build_followup_failure_message(self, *, exc: HTTPException) -> MessengerOutgoingMessage:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code")
        if code == "OPENAI_NOT_CONFIGURED":
            return MessengerOutgoingMessage(
                kind="text",
                text=DEFAULT_MESSENGER_FOLLOWUP_CONFIG_REPLY,
            )
        if code == "OPENAI_ASK_FAILED":
            return MessengerOutgoingMessage(
                kind="text",
                text=DEFAULT_MESSENGER_FOLLOWUP_UPSTREAM_REPLY,
            )
        return MessengerOutgoingMessage(kind="text", text=DEFAULT_MESSENGER_FOLLOWUP_FAILED_REPLY)


def build_default_persistent_menu() -> list[dict[str, str]]:
    return [
        {
            "type": "postback",
            "title": DEFAULT_MESSENGER_BALANCE_BUTTON_TITLE,
            "payload": SHOW_BALANCE_PAYLOAD,
        },
        {
            "type": "postback",
            "title": DEFAULT_MESSENGER_SETTINGS_BUTTON_TITLE,
            "payload": OPEN_SETTINGS_PAYLOAD,
        },
    ]


def build_default_greeting_text() -> str:
    return DEFAULT_MESSENGER_GREETING_TEXT


def build_default_get_started_payload() -> str:
    return GET_STARTED_PAYLOAD
