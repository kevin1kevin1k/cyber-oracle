"""update followups for threaded asks

Revision ID: 20260219_0005
Revises: 20260218_0004
Create Date: 2026-02-19 00:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260219_0005"
down_revision: Union[str, None] = "20260218_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("followups", sa.Column("origin_request_id", sa.String(length=64), nullable=True))
    op.add_column("followups", sa.Column("used_question_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_followups_used_question_id_questions",
        "followups",
        "questions",
        ["used_question_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_followups_status_created_at",
        "followups",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_followups_status_created_at", table_name="followups")
    op.drop_constraint("fk_followups_used_question_id_questions", "followups", type_="foreignkey")
    op.drop_column("followups", "used_question_id")
    op.drop_column("followups", "origin_request_id")
