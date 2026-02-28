import os
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import AskOpenAIConfigError, AskOpenAIRuntimeError, app
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.order import Order
from app.models.question import Question
from app.models.session_record import SessionRecord
from app.models.user import User
from app.security import create_access_token

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run ask credit tests on primary database 'elin'.")


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
        CreditWallet.__table__,
        Order.__table__,
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
        session.query(Order).delete()
        session.query(Answer).delete()
        session.query(Followup).delete()
        session.query(Question).delete()
        session.query(SessionRecord).delete()
        session.query(CreditWallet).delete()
        session.query(User).delete()
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session: Session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_verified_token_with_wallet(db_session: Session, balance: int) -> tuple[str, uuid.UUID]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    wallet = CreditWallet(user_id=user.id, balance=balance)
    db_session.add(wallet)
    db_session.flush()

    token = create_access_token(
        subject=str(user.id),
        email=user.email,
        email_verified=True,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    db_session.add(
        SessionRecord(
            user_id=user.id,
            jti=claims["jti"],
            issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )
    )
    db_session.commit()
    return token, user.id


def _count_tx(db_session: Session, user_id: uuid.UUID, action: str, key: str) -> int:
    return db_session.scalar(
        select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.action == action,
            CreditTransaction.idempotency_key == key,
        )
    )


@pytest.fixture(autouse=True)
def _stub_openai_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.main._generate_answer_from_openai_file_search",
        lambda _: ("測試回答（stub）", "rag", ["延伸 A", "延伸 B", "延伸 C"]),
    )


def test_ask_insufficient_credit_returns_402(client: TestClient, db_session: Session) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=0)
    key = "ask-insufficient"

    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "INSUFFICIENT_CREDIT"
    assert _count_tx(db_session, user_id, "capture", key) == 0
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 0


def test_ask_success_reserve_and_capture(client: TestClient, db_session: Session) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=2)
    key = "ask-success"

    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "rag"
    assert len(payload["followup_options"]) == 3
    assert len({option["content"] for option in payload["followup_options"]}) == 3

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    assert _count_tx(db_session, user_id, "reserve", key) == 1
    assert _count_tx(db_session, user_id, "capture", key) == 1
    assert _count_tx(db_session, user_id, "refund", key) == 0

    question = db_session.scalar(
        select(Question).where(Question.user_id == user_id, Question.idempotency_key == key)
    )
    assert question is not None
    assert question.status == "succeeded"

    answer = db_session.scalar(select(Answer).where(Answer.question_id == question.id))
    assert answer is not None
    assert (answer.main_pct, answer.secondary_pct, answer.reference_pct) == (70, 20, 10)
    followups = db_session.scalars(
        select(Followup).where(Followup.question_id == question.id)
    ).all()
    assert len(followups) == 3


def test_ask_accepts_less_than_three_followups(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=2)
    key = "ask-less-followups"

    monkeypatch.setattr(
        "app.main._generate_answer_from_openai_file_search",
        lambda _: ("少量延伸測試", "rag", ["延伸 1", "延伸 2"]),
    )

    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["content"] for item in payload["followup_options"]] == ["延伸 1", "延伸 2"]

    question = db_session.scalar(
        select(Question).where(Question.user_id == user_id, Question.idempotency_key == key)
    )
    assert question is not None
    followups = db_session.scalars(
        select(Followup)
        .where(Followup.question_id == question.id)
        .order_by(Followup.created_at.asc(), Followup.id.asc())
    ).all()
    assert [item.content for item in followups] == ["延伸 1", "延伸 2"]


def test_ask_retry_same_idempotency_key_no_double_charge(
    client: TestClient,
    db_session: Session,
) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=2)
    key = "ask-retry"

    first = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "重試測試", "lang": "zh", "mode": "analysis"},
    )
    second = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "重試測試", "lang": "zh", "mode": "analysis"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["request_id"] == second.json()["request_id"]

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    assert _count_tx(db_session, user_id, "reserve", key) == 1
    assert _count_tx(db_session, user_id, "capture", key) == 1
    assert _count_tx(db_session, user_id, "refund", key) == 0


def test_ask_failure_triggers_refund(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=1)
    key = "ask-failure"

    def _raise(_: str) -> tuple[str, str, list[str]]:
        raise AskOpenAIRuntimeError("openai runtime failed")

    monkeypatch.setattr("app.main._generate_answer_from_openai_file_search", _raise)

    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "會失敗", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "OPENAI_ASK_FAILED"

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    assert _count_tx(db_session, user_id, "reserve", key) == 1
    assert _count_tx(db_session, user_id, "capture", key) == 0
    assert _count_tx(db_session, user_id, "refund", key) == 1


def test_ask_openai_config_error_triggers_refund(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, user_id = _make_verified_token_with_wallet(db_session=db_session, balance=1)
    key = "ask-openai-config-error"

    def _raise(_: str) -> tuple[str, str, list[str]]:
        raise AskOpenAIConfigError("OPENAI_API_KEY is required")

    monkeypatch.setattr("app.main._generate_answer_from_openai_file_search", _raise)

    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"question": "設定缺失", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "OPENAI_NOT_CONFIGURED"

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    assert _count_tx(db_session, user_id, "reserve", key) == 1
    assert _count_tx(db_session, user_id, "capture", key) == 0
    assert _count_tx(db_session, user_id, "refund", key) == 1
