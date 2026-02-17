"""create core domain tables

Revision ID: 20260217_0002
Revises: 20260216_0001
Create Date: 2026-02-17 02:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260217_0002"
down_revision: Union[str, None] = "20260216_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_sessions_jti"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)
    op.create_index("ix_sessions_revoked_at", "sessions", ["revoked_at"], unique=False)

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('rag', 'rule', 'openai', 'mock')", name="ck_questions_source_valid"),
        sa.CheckConstraint(
            "status IN ('submitted', 'succeeded', 'failed')",
            name="ck_questions_status_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_questions_request_id"),
    )
    op.create_index("ix_questions_user_id_created_at", "questions", ["user_id", "created_at"], unique=False)
    op.create_index("ix_questions_idempotency_key", "questions", ["idempotency_key"], unique=False)

    op.create_table(
        "answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("main_pct", sa.Integer(), nullable=False),
        sa.Column("secondary_pct", sa.Integer(), nullable=False),
        sa.Column("reference_pct", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("main_pct + secondary_pct + reference_pct = 100", name="ck_answers_pct_total_100"),
        sa.CheckConstraint("main_pct >= 0 AND main_pct <= 100", name="ck_answers_main_pct_range"),
        sa.CheckConstraint("reference_pct >= 0 AND reference_pct <= 100", name="ck_answers_reference_pct_range"),
        sa.CheckConstraint("secondary_pct >= 0 AND secondary_pct <= 100", name="ck_answers_secondary_pct_range"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", name="uq_answers_question_id"),
    )
    op.create_index("ix_answers_created_at", "answers", ["created_at"], unique=False)

    op.create_table(
        "credit_wallets",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_credit_wallets_balance_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_size", sa.Integer(), nullable=False),
        sa.Column("amount_twd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_twd IN (168, 358, 518)", name="ck_orders_amount_twd_valid"),
        sa.CheckConstraint("package_size IN (1, 3, 5)", name="ck_orders_package_size_valid"),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'refunded')",
            name="ck_orders_status_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_id_idempotency_key"),
    )
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"], unique=False)
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)

    op.create_table(
        "credit_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "action IN ('reserve', 'capture', 'refund', 'grant', 'purchase')",
            name="ck_credit_transactions_action_valid",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "action",
            "idempotency_key",
            name="uq_credit_transactions_user_action_idempotency_key",
        ),
    )
    op.create_index(
        "ix_credit_transactions_user_id_created_at",
        "credit_transactions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_credit_transactions_request_id", "credit_transactions", ["request_id"], unique=False)
    op.create_index("ix_credit_transactions_question_id", "credit_transactions", ["question_id"], unique=False)

    op.create_table(
        "followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'used')", name="ck_followups_status_valid"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_followups_user_id_created_at", "followups", ["user_id", "created_at"], unique=False)
    op.create_index("ix_followups_question_id", "followups", ["question_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_followups_question_id", table_name="followups")
    op.drop_index("ix_followups_user_id_created_at", table_name="followups")
    op.drop_table("followups")

    op.drop_index("ix_credit_transactions_question_id", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_request_id", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_user_id_created_at", table_name="credit_transactions")
    op.drop_table("credit_transactions")

    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
    op.drop_table("orders")

    op.drop_table("credit_wallets")

    op.drop_index("ix_answers_created_at", table_name="answers")
    op.drop_table("answers")

    op.drop_index("ix_questions_idempotency_key", table_name="questions")
    op.drop_index("ix_questions_user_id_created_at", table_name="questions")
    op.drop_table("questions")

    op.drop_index("ix_sessions_revoked_at", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
