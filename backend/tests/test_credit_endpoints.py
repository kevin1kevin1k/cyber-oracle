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
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
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
        pytest.skip("Refusing to run credit endpoint tests on primary database 'elin'.")


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
        Order.__table__,
        CreditWallet.__table__,
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
        session.query(CreditWallet).delete()
        session.query(Order).delete()
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


def test_credits_balance_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/credits/balance")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_credits_balance_defaults_to_zero_without_wallet(
    client: TestClient,
    db_session: Session,
) -> None:
    _, token = _create_user_with_token(db_session)

    response = client.get(
        "/api/v1/credits/balance",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["balance"] == 0
    assert payload["updated_at"] is None


def test_credits_balance_returns_wallet_data(client: TestClient, db_session: Session) -> None:
    user, token = _create_user_with_token(db_session)
    db_session.add(CreditWallet(user_id=user.id, balance=9))
    db_session.commit()

    response = client.get(
        "/api/v1/credits/balance",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["balance"] == 9
    assert isinstance(payload["updated_at"], str)


def test_credits_transactions_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/credits/transactions")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_credits_transactions_returns_user_only_with_pagination(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    other_user, _ = _create_user_with_token(db_session)

    now = datetime.now(UTC)
    db_session.add_all(
        [
            CreditTransaction(
                user_id=user.id,
                action="reserve",
                amount=-1,
                reason_code="ASK_RESERVED",
                idempotency_key="k-1",
                request_id="req-1",
                created_at=now - timedelta(minutes=2),
            ),
            CreditTransaction(
                user_id=user.id,
                action="capture",
                amount=-1,
                reason_code="ASK_CAPTURED",
                idempotency_key="k-1",
                request_id="req-1",
                created_at=now - timedelta(minutes=1),
            ),
            CreditTransaction(
                user_id=user.id,
                action="refund",
                amount=1,
                reason_code="ASK_REFUNDED",
                idempotency_key="k-2",
                request_id="req-2",
                created_at=now,
            ),
            CreditTransaction(
                user_id=other_user.id,
                action="grant",
                amount=5,
                reason_code="MANUAL_GRANT",
                idempotency_key="other-k",
                request_id="other-req",
                created_at=now + timedelta(seconds=1),
            ),
        ]
    )
    db_session.commit()

    first_page = client.get(
        "/api/v1/credits/transactions?limit=2&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["items"][0]["action"] == "refund"
    assert payload["items"][1]["action"] == "capture"

    second_page = client.get(
        "/api/v1/credits/transactions?limit=2&offset=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_page.status_code == 200
    payload2 = second_page.json()
    assert payload2["total"] == 3
    assert len(payload2["items"]) == 1
    assert payload2["items"][0]["action"] == "reserve"
