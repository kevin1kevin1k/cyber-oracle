"""add messenger webhook receipts table

Revision ID: 20260331_0010
Revises: 20260323_0009
Create Date: 2026-03-31 11:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260331_0010"
down_revision: Union[str, None] = "20260323_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messenger_webhook_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("delivery_key", sa.String(length=255), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("psid", sa.String(length=128), nullable=True),
        sa.Column("page_id", sa.String(length=128), nullable=True),
        sa.Column("message_mid", sa.String(length=255), nullable=True),
        sa.Column("payload_summary", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_status", sa.String(length=16), nullable=False),
        sa.Column("processing_status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('request', 'message', 'quick_reply', 'postback', 'unsupported')",
            name="ck_messenger_webhook_receipts_event_type_valid",
        ),
        sa.CheckConstraint(
            "signature_status IN ('skipped', 'valid', 'invalid')",
            name="ck_messenger_webhook_receipts_signature_status_valid",
        ),
        sa.CheckConstraint(
            "processing_status IN ('accepted', 'processing', 'succeeded', 'failed', 'duplicate_ignored')",
            name="ck_messenger_webhook_receipts_processing_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_messenger_webhook_receipts_delivery_key",
        "messenger_webhook_receipts",
        ["delivery_key"],
        unique=True,
    )
    op.create_index(
        "ix_messenger_webhook_receipts_message_mid",
        "messenger_webhook_receipts",
        ["message_mid"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_webhook_receipts_received_at",
        "messenger_webhook_receipts",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        "ix_messenger_webhook_receipts_psid_page_id",
        "messenger_webhook_receipts",
        ["psid", "page_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_messenger_webhook_receipts_psid_page_id",
        table_name="messenger_webhook_receipts",
    )
    op.drop_index(
        "ix_messenger_webhook_receipts_received_at",
        table_name="messenger_webhook_receipts",
    )
    op.drop_index(
        "ix_messenger_webhook_receipts_message_mid",
        table_name="messenger_webhook_receipts",
    )
    op.drop_index(
        "uq_messenger_webhook_receipts_delivery_key",
        table_name="messenger_webhook_receipts",
    )
    op.drop_table("messenger_webhook_receipts")
