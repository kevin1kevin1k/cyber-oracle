import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.order import Order
from app.models.question import Question
from app.models.session_record import SessionRecord
from app.models.user import User

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run schema tests on primary database 'elin'.")


@pytest.fixture(scope="module")
def engine():
    _ensure_safe_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as _:
            pass
    except OperationalError:
        pytest.skip(f"PostgreSQL is not available at {TEST_DATABASE_URL}")

    tables = [
        User.__table__,
        SessionRecord.__table__,
        Question.__table__,
        Answer.__table__,
        Order.__table__,
        CreditWallet.__table__,
        CreditTransaction.__table__,
        Followup.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    yield engine
    Base.metadata.drop_all(bind=engine, tables=tables)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        session.query(CreditTransaction).delete()
        session.query(Followup).delete()
        session.query(Answer).delete()
        session.query(Question).delete()
        session.query(Order).delete()
        session.query(SessionRecord).delete()
        session.query(CreditWallet).delete()
        session.query(User).delete()
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


def _create_user(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_core_tables_exist(engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    assert "sessions" in table_names
    assert "questions" in table_names
    assert "answers" in table_names
    assert "credit_wallets" in table_names
    assert "credit_transactions" in table_names
    assert "orders" in table_names
    assert "followups" in table_names


def test_credit_wallet_balance_must_be_non_negative(db_session: Session) -> None:
    user = _create_user(db_session)
    wallet = CreditWallet(user_id=user.id, balance=-1)
    db_session.add(wallet)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_orders_user_idempotency_unique(db_session: Session) -> None:
    user = _create_user(db_session)
    order1 = Order(
        user_id=user.id,
        package_size=1,
        amount_twd=168,
        status="pending",
        idempotency_key="same-key",
    )
    order2 = Order(
        user_id=user.id,
        package_size=1,
        amount_twd=168,
        status="pending",
        idempotency_key="same-key",
    )
    db_session.add(order1)
    db_session.commit()

    db_session.add(order2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_credit_transactions_user_action_idempotency_unique(db_session: Session) -> None:
    user = _create_user(db_session)
    question = Question(
        user_id=user.id,
        question_text="test question",
        lang="zh",
        mode="analysis",
        status="submitted",
        source="mock",
        request_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    db_session.add(question)
    db_session.commit()

    tx1 = CreditTransaction(
        user_id=user.id,
        question_id=question.id,
        action="reserve",
        amount=-1,
        reason_code="ASK_RESERVED",
        idempotency_key="reserve-key",
        request_id=str(uuid.uuid4()),
    )
    tx2 = CreditTransaction(
        user_id=user.id,
        question_id=question.id,
        action="reserve",
        amount=-1,
        reason_code="ASK_RESERVED",
        idempotency_key="reserve-key",
        request_id=str(uuid.uuid4()),
    )
    db_session.add(tx1)
    db_session.commit()

    db_session.add(tx2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_session_jti_unique(db_session: Session) -> None:
    user = _create_user(db_session)
    now = datetime.now(UTC)
    s1 = SessionRecord(
        user_id=user.id,
        jti="shared-jti",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    s2 = SessionRecord(
        user_id=user.id,
        jti="shared-jti",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(s1)
    db_session.commit()

    db_session.add(s2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
