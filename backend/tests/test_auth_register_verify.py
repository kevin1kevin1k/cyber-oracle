import os
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.auth import issue_user_session
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.session_record import SessionRecord
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

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, SessionRecord.__table__])
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
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


def _create_user(db_session: Session) -> User:
    user = User(id=uuid.uuid4(), channel="messenger", channel_user_id=f"test:{uuid.uuid4()}")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/register", {"email": "user@example.com", "password": "Password123"}),
        ("/api/v1/auth/login", {"email": "user@example.com", "password": "Password123"}),
        ("/api/v1/auth/forgot-password", {"email": "user@example.com"}),
        ("/api/v1/auth/reset-password", {"token": "reset-token", "new_password": "Password123"}),
        ("/api/v1/auth/resend-verification", {"email": "user@example.com"}),
        ("/api/v1/auth/verify-email", {"token": "verify-token"}),
    ],
)
def test_email_password_auth_flows_are_disabled(
    client: TestClient,
    path: str,
    payload: dict[str, str],
) -> None:
    response = client.post(path, json=payload)

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "AUTH_FLOW_DISABLED"


def test_logout_revokes_session_and_invalidates_token(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _create_user(db_session)
    access_token = issue_user_session(db=db_session, user_id=user.id)
    claims = jwt.decode(access_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 204

    session_record = db_session.scalar(
        select(SessionRecord).where(SessionRecord.jti == claims["jti"])
    )
    assert session_record is not None
    assert session_record.revoked_at is not None

    ask_after_logout = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )
    assert ask_after_logout.status_code == 401
    assert ask_after_logout.json()["detail"]["code"] == "UNAUTHORIZED"
