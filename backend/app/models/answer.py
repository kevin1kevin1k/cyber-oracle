import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint("main_pct >= 0 AND main_pct <= 100", name="ck_answers_main_pct_range"),
        CheckConstraint(
            "secondary_pct >= 0 AND secondary_pct <= 100",
            name="ck_answers_secondary_pct_range",
        ),
        CheckConstraint(
            "reference_pct >= 0 AND reference_pct <= 100",
            name="ck_answers_reference_pct_range",
        ),
        CheckConstraint(
            "main_pct + secondary_pct + reference_pct = 100",
            name="ck_answers_pct_total_100",
        ),
        Index("ix_answers_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    main_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    secondary_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
