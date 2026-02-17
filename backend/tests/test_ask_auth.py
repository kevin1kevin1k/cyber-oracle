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
        pytest.skip("Refusing to run ask auth tests on primary database 'elin'.")


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


def _make_token_with_session(
    db_session: Session,
    email_verified: bool,
    wallet_balance: int | None = None,
) -> str:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=email_verified,
    )
    db_session.add(user)
    db_session.flush()

    if wallet_balance is not None:
        db_session.add(CreditWallet(user_id=user.id, balance=wallet_balance))

    db_session.commit()

    token = create_access_token(
        subject=str(user.id),
        email=user.email,
        email_verified=email_verified,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    session_record = SessionRecord(
        user_id=user.id,
        jti=claims["jti"],
        issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
    db_session.add(session_record)
    db_session.commit()
    return token


def _make_legacy_token_without_jti(email_verified: bool) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "legacy@example.com",
        "email_verified": email_verified,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=60)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_ask_unauthorized_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ask",
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_ask_legacy_token_without_jti_returns_401(client: TestClient) -> None:
    token = _make_legacy_token_without_jti(email_verified=True)
    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_ask_unverified_email_returns_403(client: TestClient, db_session: Session) -> None:
    token = _make_token_with_session(db_session=db_session, email_verified=False)
    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"


def test_ask_verified_email_returns_200(client: TestClient, db_session: Session) -> None:
    token = _make_token_with_session(db_session=db_session, email_verified=True, wallet_balance=1)
    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "mock"
    assert len(payload["layer_percentages"]) == 3
