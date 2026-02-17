import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models.user import User

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run auth tests on primary database 'elin'.")


@pytest.fixture(scope="module")
def engine():
    _ensure_safe_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as _:
            pass
    except OperationalError:
        pytest.skip(f"PostgreSQL is not available at {TEST_DATABASE_URL}")

    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    yield engine
    Base.metadata.drop_all(bind=engine, tables=[User.__table__])
    engine.dispose()


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
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


def test_register_success(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "NewUser@example.com", "password": "Password123"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == "newuser@example.com"
    assert payload["email_verified"] is False
    assert payload["verification_token"]

    user = db_session.scalar(select(User).where(User.email == "newuser@example.com"))
    assert user is not None
    assert user.email_verified is False
    assert user.verify_token == payload["verification_token"]
    assert user.password_hash != "Password123"


def test_register_duplicate_email_returns_409(client: TestClient, db_session: Session) -> None:
    db_session.add(
        User(
            id=uuid.uuid4(),
            email="dup@example.com",
            password_hash="hash",
            email_verified=False,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "Password123"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"


def test_verify_email_success(client: TestClient, db_session: Session) -> None:
    user = User(
        id=uuid.uuid4(),
        email="verify@example.com",
        password_hash="hash",
        email_verified=False,
        verify_token="valid-token",
        verify_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(user)
    db_session.commit()

    response = client.post("/api/v1/auth/verify-email", json={"token": "valid-token"})
    assert response.status_code == 200
    assert response.json()["status"] == "verified"

    db_session.refresh(user)
    assert user.email_verified is True
    assert user.verify_token is None
    assert user.verify_token_expires_at is None


def test_verify_email_invalid_or_expired_returns_400(
    client: TestClient,
    db_session: Session,
) -> None:
    expired = User(
        id=uuid.uuid4(),
        email="expired@example.com",
        password_hash="hash",
        email_verified=False,
        verify_token="expired-token",
        verify_token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(expired)
    db_session.commit()

    invalid_response = client.post("/api/v1/auth/verify-email", json={"token": "not-found"})
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"

    expired_response = client.post("/api/v1/auth/verify-email", json={"token": "expired-token"})
    assert expired_response.status_code == 400
    assert expired_response.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"
