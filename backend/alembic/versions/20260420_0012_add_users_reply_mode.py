"""add users reply mode

Revision ID: 20260420_0012
Revises: 20260331_0011
Create Date: 2026-04-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260420_0012"
down_revision = "20260331_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "reply_mode",
            sa.String(length=32),
            nullable=False,
            server_default="structured",
        ),
    )
    op.create_check_constraint(
        "ck_users_reply_mode_valid",
        "users",
        "reply_mode IN ('structured', 'free')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_reply_mode_valid", "users", type_="check")
    op.drop_column("users", "reply_mode")
