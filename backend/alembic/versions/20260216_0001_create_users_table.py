"""create users table

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260216_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verify_token", sa.Text(), nullable=True),
        sa.Column("verify_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("channel_user_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email_unique", "users", ["email"], unique=True)
    op.create_index(
        "ix_users_channel_channel_user_id_unique",
        "users",
        ["channel", "channel_user_id"],
        unique=True,
        postgresql_where=sa.text("channel IS NOT NULL AND channel_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_channel_channel_user_id_unique", table_name="users")
    op.drop_index("ix_users_email_unique", table_name="users")
    op.drop_table("users")
