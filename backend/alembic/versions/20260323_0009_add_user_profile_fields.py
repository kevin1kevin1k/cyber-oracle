"""add user profile fields for ask personalization

Revision ID: 20260323_0009
Revises: 20260322_0008
Create Date: 2026-03-23 11:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260323_0009"
down_revision: Union[str, None] = "20260322_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("mother_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "mother_name")
    op.drop_column("users", "full_name")
