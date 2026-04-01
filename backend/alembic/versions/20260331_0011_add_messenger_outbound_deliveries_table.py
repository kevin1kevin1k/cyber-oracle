"""add messenger outbound deliveries table

Revision ID: 20260331_0011
Revises: 20260331_0010
Create Date: 2026-03-31 14:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260331_0011"
down_revision: Union[str, None] = "20260331_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messenger_outbound_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("delivery_key", sa.String(length=255), nullable=False),
        sa.Column("psid", sa.String(length=128), nullable=False),
        sa.Column("message_kind", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'dead_letter')",
            name="ck_messenger_outbound_deliveries_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["messenger_webhook_receipts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_messenger_outbound_deliveries_delivery_key",
        "messenger_outbound_deliveries",
        ["delivery_key"],
        unique=True,
    )
    op.create_index(
        "ix_messenger_outbound_deliveries_receipt_id_created_at",
        "messenger_outbound_deliveries",
        ["receipt_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_outbound_deliveries_status_created_at",
        "messenger_outbound_deliveries",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_outbound_deliveries_psid",
        "messenger_outbound_deliveries",
        ["psid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_messenger_outbound_deliveries_psid",
        table_name="messenger_outbound_deliveries",
    )
    op.drop_index(
        "ix_messenger_outbound_deliveries_status_created_at",
        table_name="messenger_outbound_deliveries",
    )
    op.drop_index(
        "ix_messenger_outbound_deliveries_receipt_id_created_at",
        table_name="messenger_outbound_deliveries",
    )
    op.drop_index(
        "uq_messenger_outbound_deliveries_delivery_key",
        table_name="messenger_outbound_deliveries",
    )
    op.drop_table("messenger_outbound_deliveries")
