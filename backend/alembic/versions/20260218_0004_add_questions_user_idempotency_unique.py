"""add unique constraint for questions user idempotency key

Revision ID: 20260218_0004
Revises: 20260217_0003
Create Date: 2026-02-18 10:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260218_0004"
down_revision: Union[str, None] = "20260217_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_questions_user_id_idempotency_key",
        "questions",
        ["user_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_questions_user_id_idempotency_key", "questions", type_="unique")
