"""add messenger pending asks table

Revision ID: 20260321_0007
Revises: 20260311_0006
Create Date: 2026-03-21 02:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260321_0007"
down_revision: Union[str, None] = "20260311_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messenger_pending_asks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("messenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("used_question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'used')",
            name="ck_messenger_pending_asks_status_valid",
        ),
        sa.ForeignKeyConstraint(["messenger_identity_id"], ["messenger_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_question_id"], ["questions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_messenger_pending_asks_user_id_idempotency_key",
        ),
    )
    op.create_index(
        "ix_messenger_pending_asks_user_id_created_at",
        "messenger_pending_asks",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_pending_asks_identity_id",
        "messenger_pending_asks",
        ["messenger_identity_id"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_pending_asks_status_created_at",
        "messenger_pending_asks",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messenger_pending_asks_status_created_at", table_name="messenger_pending_asks")
    op.drop_index("ix_messenger_pending_asks_identity_id", table_name="messenger_pending_asks")
    op.drop_index("ix_messenger_pending_asks_user_id_created_at", table_name="messenger_pending_asks")
    op.drop_table("messenger_pending_asks")
