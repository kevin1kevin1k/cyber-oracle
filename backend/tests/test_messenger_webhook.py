import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models.messenger_identity import MessengerIdentity
from app.models.user import User

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run messenger webhook tests on primary database 'elin'.")


@pytest.fixture(scope="module")
def engine():
    _ensure_safe_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as _:
            pass
    except OperationalError:
        pytest.skip(f"PostgreSQL is not available at {TEST_DATABASE_URL}")

    tables = [User.__table__, MessengerIdentity.__table__]
    Base.metadata.create_all(bind=engine, tables=tables)
    yield engine
    Base.metadata.drop_all(bind=engine, tables=tables)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_local()
    try:
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


@pytest.fixture(autouse=True)
def _messenger_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "messenger_enabled", True)
    monkeypatch.setattr(settings, "meta_verify_token", "verify-token")
    monkeypatch.setattr(settings, "messenger_outbound_mode", "noop")
    monkeypatch.setattr(settings, "messenger_verify_signature", False)
    monkeypatch.setattr(settings, "meta_app_secret", None)


def test_webhook_verify_success(client: TestClient) -> None:
    response = client.get(
        "/api/v1/messenger/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "abc123",
        },
    )

    assert response.status_code == 200
    assert response.text == "abc123"


def test_webhook_verify_failure(client: TestClient) -> None:
    response = client.get(
        "/api/v1/messenger/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "abc123",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WEBHOOK_VERIFY_FAILED"


def test_webhook_disabled_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "messenger_enabled", False)

    response = client.get(
        "/api/v1/messenger/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "abc123",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MESSENGER_DISABLED"


def test_webhook_post_message_event_creates_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "time": 1700000000,
                "messaging": [
                    {
                        "sender": {"id": "psid-001"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1700000000,
                        "message": {"mid": "m_1", "text": "hello"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["processed"] == 1

    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-001",
            MessengerIdentity.page_id == "page-1",
        )
    )
    assert identity is not None
    assert identity.status == "unlinked"


def test_webhook_post_postback_event(client: TestClient) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-2",
                "time": 1700001000,
                "messaging": [
                    {
                        "sender": {"id": "psid-002"},
                        "recipient": {"id": "page-2"},
                        "timestamp": 1700001000,
                        "postback": {"payload": "START"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["processed"] == 1


def test_webhook_post_quick_reply_event(client: TestClient) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-3",
                "time": 1700002000,
                "messaging": [
                    {
                        "sender": {"id": "psid-003"},
                        "recipient": {"id": "page-3"},
                        "timestamp": 1700002000,
                        "message": {
                            "mid": "m_3",
                            "text": "pick",
                            "quick_reply": {"payload": "QR_PAYLOAD"},
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["processed"] == 1


def test_webhook_signature_invalid_returns_403(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "messenger_verify_signature", True)
    monkeypatch.setattr(settings, "meta_app_secret", "secret")

    payload = {
        "object": "page",
        "entry": [],
    }
    response = client.post(
        "/api/v1/messenger/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


def test_webhook_post_invalid_payload_returns_422(client: TestClient) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "recipient": {"id": "page-1"},
                        "message": {"text": "missing sender"},
                    }
                ],
            }
        ],
    }
    response = client.post("/api/v1/messenger/webhook", json=payload)
    assert response.status_code == 422
