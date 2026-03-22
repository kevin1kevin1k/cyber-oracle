"""make users email and password nullable for messenger primary auth

Revision ID: 20260322_0008
Revises: 20260321_0007
Create Date: 2026-03-22 10:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260322_0008"
down_revision: Union[str, None] = "20260321_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)
