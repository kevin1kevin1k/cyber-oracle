import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessengerWebhookReceipt(Base):
    __tablename__ = "messenger_webhook_receipts"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('request', 'message', 'quick_reply', 'postback', 'unsupported')",
            name="ck_messenger_webhook_receipts_event_type_valid",
        ),
        CheckConstraint(
            "signature_status IN ('skipped', 'valid', 'invalid')",
            name="ck_messenger_webhook_receipts_signature_status_valid",
        ),
        CheckConstraint(
            "processing_status IN "
            "('accepted', 'processing', 'succeeded', 'failed', 'duplicate_ignored')",
            name="ck_messenger_webhook_receipts_processing_status_valid",
        ),
        Index(
            "uq_messenger_webhook_receipts_delivery_key",
            "delivery_key",
            unique=True,
        ),
        Index(
            "ix_messenger_webhook_receipts_message_mid",
            "message_mid",
        ),
        Index(
            "ix_messenger_webhook_receipts_received_at",
            "received_at",
        ),
        Index(
            "ix_messenger_webhook_receipts_psid_page_id",
            "psid",
            "page_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_key: Mapped[str] = mapped_column(String(255), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    psid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message_mid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
