import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
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
        pytest.skip("Refusing to run history endpoint tests on primary database 'elin'.")


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
        CreditTransaction.__table__,
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
        session.query(Question).delete()
        session.query(SessionRecord).delete()
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


def _create_user_with_token(db_session: Session) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
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
    return user, token


def _create_question_with_answer(
    db_session: Session,
    *,
    user_id,
    question_text: str,
    answer_text: str,
    created_at: datetime,
    request_id: str,
    idempotency_key: str,
    status: str = "succeeded",
) -> Question:
    question = Question(
        user_id=user_id,
        question_text=question_text,
        lang="zh",
        mode="analysis",
        status=status,
        source="mock",
        request_id=request_id,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )
    db_session.add(question)
    db_session.flush()
    db_session.add(
        Answer(
            question_id=question.id,
            answer_text=answer_text,
            main_pct=70,
            secondary_pct=20,
            reference_pct=10,
            created_at=created_at,
        )
    )
    return question


def test_history_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/history/questions")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_history_returns_user_only_with_preview_pagination_and_charged_credits(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    other_user, _ = _create_user_with_token(db_session)
    now = datetime.now(UTC)

    oldest = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="最舊問題",
        answer_text="最舊答案",
        created_at=now - timedelta(minutes=3),
        request_id="req-oldest",
        idempotency_key="k-oldest",
    )
    middle = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="中間問題",
        answer_text="a" * 170,
        created_at=now - timedelta(minutes=2),
        request_id="req-middle",
        idempotency_key="k-middle",
    )
    latest = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="最新問題",
        answer_text="最新答案",
        created_at=now - timedelta(minutes=1),
        request_id="req-latest",
        idempotency_key="k-latest",
    )
    _create_question_with_answer(
        db_session,
        user_id=other_user.id,
        question_text="其他人問題",
        answer_text="其他人答案",
        created_at=now,
        request_id="req-other",
        idempotency_key="k-other",
    )
    _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="失敗問題",
        answer_text="不應被回傳",
        created_at=now - timedelta(seconds=30),
        request_id="req-failed",
        idempotency_key="k-failed",
        status="failed",
    )
    db_session.add(
        CreditTransaction(
            user_id=user.id,
            question_id=latest.id,
            action="capture",
            amount=-1,
            reason_code="ASK_CAPTURED",
            idempotency_key="cap-latest",
            request_id="req-cap-latest",
            created_at=now - timedelta(minutes=1),
        )
    )
    db_session.add(
        CreditTransaction(
            user_id=user.id,
            question_id=middle.id,
            action="capture",
            amount=-1,
            reason_code="ASK_CAPTURED",
            idempotency_key="cap-middle",
            request_id="req-cap-middle",
            created_at=now - timedelta(minutes=2),
        )
    )
    db_session.commit()

    first_page = client.get(
        "/api/v1/history/questions?limit=2&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["items"][0]["question_text"] == "最新問題"
    assert payload["items"][0]["charged_credits"] == 1
    assert payload["items"][1]["question_text"] == "中間問題"
    assert payload["items"][1]["charged_credits"] == 1
    assert payload["items"][1]["answer_preview"].endswith("...")
    assert len(payload["items"][1]["answer_preview"]) == 163

    second_page = client.get(
        "/api/v1/history/questions?limit=2&offset=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_page.status_code == 200
    payload2 = second_page.json()
    assert payload2["total"] == 3
    assert len(payload2["items"]) == 1
    assert payload2["items"][0]["question_id"] == str(oldest.id)
    assert payload2["items"][0]["charged_credits"] == 0
