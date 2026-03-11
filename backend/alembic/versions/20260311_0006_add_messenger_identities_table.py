"""add messenger identities table

Revision ID: 20260311_0006
Revises: 20260219_0005
Create Date: 2026-03-11 23:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260311_0006"
down_revision: Union[str, None] = "20260219_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messenger_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=32), server_default=sa.text("'messenger'"), nullable=False),
        sa.Column("psid", sa.String(length=128), nullable=False),
        sa.Column("page_id", sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'unlinked'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("platform IN ('messenger')", name="ck_messenger_identities_platform_valid"),
        sa.CheckConstraint(
            "status IN ('unlinked', 'linked', 'blocked')",
            name="ck_messenger_identities_status_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_messenger_identities_platform_psid_page_id",
        "messenger_identities",
        ["platform", "psid", "page_id"],
        unique=True,
    )
    op.create_index("ix_messenger_identities_user_id", "messenger_identities", ["user_id"], unique=False)
    op.create_index(
        "ix_messenger_identities_last_interacted_at",
        "messenger_identities",
        ["last_interacted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messenger_identities_last_interacted_at", table_name="messenger_identities")
    op.drop_index("ix_messenger_identities_user_id", table_name="messenger_identities")
    op.drop_index("uq_messenger_identities_platform_psid_page_id", table_name="messenger_identities")
    op.drop_table("messenger_identities")
