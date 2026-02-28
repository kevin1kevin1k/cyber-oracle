import os
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
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
        pytest.skip("Refusing to run followup tests on primary database 'elin'.")


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
        session.query(CreditWallet).delete()
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


@pytest.fixture(autouse=True)
def _stub_openai_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.main._generate_answer_from_openai_file_search",
        lambda _: ("測試回答（stub）", "rag", ["延伸 A", "延伸 B", "延伸 C"]),
    )


def _create_verified_user_with_wallet(db_session: Session, balance: int) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(CreditWallet(user_id=user.id, balance=balance))
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


def _create_followup(db_session: Session, *, user_id: uuid.UUID, content: str) -> Followup:
    question = Question(
        user_id=user_id,
        question_text="主問題",
        lang="zh",
        mode="analysis",
        status="succeeded",
        source="mock",
        request_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    db_session.add(question)
    db_session.flush()
    followup = Followup(
        question_id=question.id,
        user_id=user_id,
        content=content,
        status="pending",
    )
    db_session.add(followup)
    db_session.commit()
    return followup


def test_followup_ask_requires_auth(client: TestClient) -> None:
    response = client.post(f"/api/v1/followups/{uuid.uuid4()}/ask")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_followup_ask_not_found(client: TestClient, db_session: Session) -> None:
    _, token = _create_verified_user_with_wallet(db_session, balance=2)
    response = client.post(
        f"/api/v1/followups/{uuid.uuid4()}/ask",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "FOLLOWUP_NOT_FOUND"


def test_followup_ask_owner_mismatch_returns_403(client: TestClient, db_session: Session) -> None:
    owner, _ = _create_verified_user_with_wallet(db_session, balance=2)
    _, token = _create_verified_user_with_wallet(db_session, balance=2)
    followup = _create_followup(db_session, user_id=owner.id, content="延伸提問 A")

    response = client.post(
        f"/api/v1/followups/{followup.id}/ask",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FOLLOWUP_OWNER_MISMATCH"


def test_followup_ask_success_marks_used_and_deducts_credit(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_verified_user_with_wallet(db_session, balance=2)
    followup = _create_followup(db_session, user_id=user.id, content="延伸提問 B")

    response = client.post(
        f"/api/v1/followups/{followup.id}/ask",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "rag"
    assert len(payload["followup_options"]) == 3

    db_followup = db_session.scalar(select(Followup).where(Followup.id == followup.id))
    assert db_followup is not None
    assert db_followup.status == "used"
    assert db_followup.used_at is not None
    assert db_followup.used_question_id is not None

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user.id))
    assert wallet is not None
    assert wallet.balance == 1

    reserve_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user.id,
        CreditTransaction.action == "reserve",
        CreditTransaction.idempotency_key == f"followup:{followup.id}",
    ).count()
    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user.id,
        CreditTransaction.action == "capture",
        CreditTransaction.idempotency_key == f"followup:{followup.id}",
    ).count()
    assert reserve_count == 1
    assert capture_count == 1


def test_followup_ask_insufficient_credit_restores_pending(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_verified_user_with_wallet(db_session, balance=0)
    followup = _create_followup(db_session, user_id=user.id, content="延伸提問 C")

    response = client.post(
        f"/api/v1/followups/{followup.id}/ask",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "INSUFFICIENT_CREDIT"

    db_followup = db_session.scalar(select(Followup).where(Followup.id == followup.id))
    assert db_followup is not None
    assert db_followup.status == "pending"
    assert db_followup.used_at is None
    assert db_followup.used_question_id is None


def test_followup_ask_already_used_returns_409(client: TestClient, db_session: Session) -> None:
    user, token = _create_verified_user_with_wallet(db_session, balance=2)
    followup = _create_followup(db_session, user_id=user.id, content="延伸提問 D")
    followup.status = "used"
    followup.used_at = datetime.now(UTC)
    db_session.add(followup)
    db_session.commit()

    response = client.post(
        f"/api/v1/followups/{followup.id}/ask",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "FOLLOWUP_ALREADY_USED"
