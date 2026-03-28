import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.auth import issue_user_session
from app.db import Base, get_db
from app.main import app
from app.models.credit_wallet import CreditWallet
from app.models.messenger_identity import MessengerIdentity
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
        pytest.skip("Refusing to run user profile tests on primary database 'elin'.")


@pytest.fixture(scope="module")
def engine():
    _ensure_safe_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as _:
            pass
    except OperationalError:
        pytest.skip(f"PostgreSQL is not available at {TEST_DATABASE_URL}")

    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            SessionRecord.__table__,
            MessengerIdentity.__table__,
            CreditWallet.__table__,
            Question.__table__,
        ],
    )
    yield engine
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            Question.__table__,
            CreditWallet.__table__,
            MessengerIdentity.__table__,
            SessionRecord.__table__,
            User.__table__,
        ],
    )
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_local()
    try:
        session.query(SessionRecord).delete()
        session.query(Question).delete()
        session.query(CreditWallet).delete()
        session.query(MessengerIdentity).delete()
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


def _create_user_with_session(
    db_session: Session,
    *,
    full_name: str | None = None,
    mother_name: str | None = None,
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        channel="messenger",
        channel_user_id=f"messenger:{uuid.uuid4()}",
        full_name=full_name,
        mother_name=mother_name,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token = issue_user_session(db=db_session, user_id=user.id)
    return user, token


def test_get_my_profile_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/me/profile")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_get_my_profile_returns_current_values(client: TestClient, db_session: Session) -> None:
    _, token = _create_user_with_session(
        db_session,
        full_name="王小明",
        mother_name="林淑芬",
    )

    response = client.get(
        "/api/v1/me/profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "full_name": "王小明",
        "mother_name": "林淑芬",
        "is_complete": True,
    }


def test_put_my_profile_updates_values_and_marks_complete(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_session(db_session)

    response = client.put(
        "/api/v1/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "  陳大文  ", "mother_name": "  黃美玉  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "full_name": "陳大文",
        "mother_name": "黃美玉",
        "is_complete": True,
    }
    db_session.refresh(user)
    assert user.full_name == "陳大文"
    assert user.mother_name == "黃美玉"


def test_put_my_profile_rejects_blank_values(client: TestClient, db_session: Session) -> None:
    _, token = _create_user_with_session(db_session)

    response = client.put(
        "/api/v1/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "   ", "mother_name": "王母"},
    )

    assert response.status_code == 422


def test_delete_my_account_deletes_user_data_and_unlinks_messenger_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_session(
        db_session,
        full_name="王小明",
        mother_name="林淑芬",
    )
    identity = MessengerIdentity(
        psid="psid-delete-me",
        page_id="page-delete-me",
        user_id=user.id,
        status="linked",
        is_active=True,
    )
    wallet = CreditWallet(user_id=user.id, balance=9)
    question = Question(
        user_id=user.id,
        question_text="測試問題",
        lang="zh",
        mode="analysis",
        status="succeeded",
        source="rag",
        request_id="request-delete-account",
        idempotency_key="delete-account-key",
    )
    db_session.add_all([identity, wallet, question])
    db_session.commit()

    response = client.delete(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204

    db_session.expire_all()

    assert db_session.get(User, user.id) is None
    assert db_session.query(SessionRecord).filter(SessionRecord.user_id == user.id).first() is None
    assert db_session.query(CreditWallet).filter(CreditWallet.user_id == user.id).first() is None
    assert db_session.query(Question).filter(Question.user_id == user.id).first() is None

    reset_identity = db_session.get(MessengerIdentity, identity.id)
    assert reset_identity is not None
    assert reset_identity.user_id is None
    assert reset_identity.status == "unlinked"
    assert reset_identity.is_active is True
    assert reset_identity.linked_at is None

    followup_response = client.get(
        "/api/v1/me/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert followup_response.status_code == 401
    assert followup_response.json()["detail"]["code"] == "UNAUTHORIZED"
