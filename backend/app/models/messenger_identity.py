import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessengerIdentity(Base):
    __tablename__ = "messenger_identities"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('messenger')",
            name="ck_messenger_identities_platform_valid",
        ),
        CheckConstraint(
            "status IN ('unlinked', 'linked', 'blocked')",
            name="ck_messenger_identities_status_valid",
        ),
        Index(
            "uq_messenger_identities_platform_psid_page_id",
            "platform",
            "psid",
            "page_id",
            unique=True,
        ),
        Index("ix_messenger_identities_user_id", "user_id"),
        Index("ix_messenger_identities_last_interacted_at", "last_interacted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, server_default="messenger")
    psid: Mapped[str] = mapped_column(String(128), nullable=False)
    page_id: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unlinked")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        default=lambda: datetime.now(UTC),
    )
