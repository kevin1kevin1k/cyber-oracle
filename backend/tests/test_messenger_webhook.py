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
from app.messenger import routes as messenger_routes
from app.messenger.client import MessengerClientError
from app.messenger.schemas import MessengerWebhookPayload
from app.messenger.security import create_messenger_link_token
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.messenger_identity import MessengerIdentity
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

    tables = [
        User.__table__,
        SessionRecord.__table__,
        Question.__table__,
        Answer.__table__,
        CreditWallet.__table__,
        CreditTransaction.__table__,
        Order.__table__,
        Followup.__table__,
        MessengerIdentity.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    yield engine
    Base.metadata.drop_all(bind=engine, tables=tables)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_local()
    try:
        session.query(CreditTransaction).delete()
        session.query(Order).delete()
        session.query(Followup).delete()
        session.query(Answer).delete()
        session.query(Question).delete()
        session.query(CreditWallet).delete()
        session.query(MessengerIdentity).delete()
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
    session_factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    original_messenger_session_local = messenger_routes.SessionLocal
    messenger_routes.SessionLocal = session_factory
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        messenger_routes.SessionLocal = original_messenger_session_local
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _messenger_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "messenger_enabled", True)
    monkeypatch.setattr(settings, "meta_verify_token", "verify-token")
    monkeypatch.setattr(settings, "messenger_outbound_mode", "noop")
    monkeypatch.setattr(settings, "messenger_verify_signature", False)
    monkeypatch.setattr(settings, "meta_app_secret", None)
    monkeypatch.setattr(settings, "messenger_web_base_url", "https://frontend.example.com")
    monkeypatch.setattr(
        "app.ask_service._generate_answer_from_openai_file_search",
        lambda _: ("測試回答（messenger）", "rag", ["延伸 A", "延伸 B", "延伸 C"]),
    )


def _create_linked_messenger_user(
    db_session: Session,
    *,
    psid: str,
    page_id: str,
    balance: int,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(CreditWallet(user_id=user.id, balance=balance))
    db_session.add(
        MessengerIdentity(
            platform="messenger",
            psid=psid,
            page_id=page_id,
            user_id=user.id,
            status="linked",
            is_active=True,
        )
    )
    db_session.commit()
    return user


def _create_verified_user_with_token(db_session: Session) -> tuple[User, str]:
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


def _create_pending_followup(
    db_session: Session,
    *,
    user_id,
    content: str = "延伸問題 A",
) -> Followup:
    question = Question(
        user_id=user_id,
        question_text="原始問題",
        lang="zh",
        mode="analysis",
        status="succeeded",
        source="rag",
        request_id=str(uuid.uuid4()),
        idempotency_key=f"seed:{uuid.uuid4()}",
    )
    db_session.add(question)
    db_session.flush()

    db_session.add(
        Answer(
            question_id=question.id,
            answer_text="原始答案",
            main_pct=70,
            secondary_pct=20,
            reference_pct=10,
        )
    )
    followup = Followup(
        question_id=question.id,
        user_id=user_id,
        content=content,
        origin_request_id=str(uuid.uuid4()),
        status="pending",
    )
    db_session.add(followup)
    db_session.commit()
    db_session.refresh(followup)
    return followup


@pytest.fixture
def outgoing_messages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []

    def _capture(*, client, psid: str, outgoing) -> None:  # noqa: ANN001
        sent.append((psid, outgoing.kind, outgoing.text))

    monkeypatch.setattr("app.messenger.routes.dispatch_outgoing_message", _capture)
    return sent


@pytest.fixture
def captured_outgoing(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    sent: list[tuple[str, object]] = []

    def _capture(*, client, psid: str, outgoing) -> None:  # noqa: ANN001
        sent.append((psid, outgoing))

    monkeypatch.setattr("app.messenger.routes.dispatch_outgoing_message", _capture)
    return sent


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


def test_webhook_post_message_event_schedules_background_processing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[MessengerWebhookPayload] = []

    def _capture_process(*, payload: MessengerWebhookPayload) -> None:
        scheduled.append(payload)

    monkeypatch.setattr("app.messenger.routes.process_webhook_events", _capture_process)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-scheduled",
                "time": 1700000002,
                "messaging": [
                    {
                        "sender": {"id": "psid-scheduled"},
                        "recipient": {"id": "page-scheduled"},
                        "timestamp": 1700000002,
                        "message": {"mid": "m_scheduled", "text": "hello"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "processed": 1}
    assert len(scheduled) == 1
    assert scheduled[0].entry[0].messaging[0].message.text == "hello"


def test_webhook_post_message_event_for_unlinked_user_returns_link_button(
    client: TestClient,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-unlinked-link",
                "time": 1700000001,
                "messaging": [
                    {
                        "sender": {"id": "psid-unlinked-link"},
                        "recipient": {"id": "page-unlinked-link"},
                        "timestamp": 1700000001,
                        "message": {"mid": "m_unlinked_link", "text": "hello"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-unlinked-link"
    assert outgoing.kind == "button_template"
    assert outgoing.text == "已收到你的訊息。請先完成網站登入與帳號綁定後再提問。"
    assert outgoing.buttons[0]["title"] == "登入並綁定"
    assert outgoing.buttons[0]["url"].startswith("https://frontend.example.com/messenger/link?token=")


def test_webhook_post_message_event_for_linked_user_runs_ask_flow(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-linked-1",
        page_id="page-linked-1",
        balance=2,
    )
    user_id = user.id
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-1",
                "time": 1700000100,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-1"},
                        "recipient": {"id": "page-linked-1"},
                        "timestamp": 1700000100,
                        "message": {
                            "mid": "m_linked_1",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user_id,
        CreditTransaction.action == "capture",
    ).count()
    assert capture_count == 1


def test_webhook_post_message_event_with_same_mid_is_idempotent(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-linked-2",
        page_id="page-linked-2",
        balance=2,
    )
    user_id = user.id
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-2",
                "time": 1700000200,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-2"},
                        "recipient": {"id": "page-linked-2"},
                        "timestamp": 1700000200,
                        "message": {
                            "mid": "m_linked_same",
                            "text": "同一個事件重送",
                        },
                    }
                ],
            }
        ],
    }

    first = client.post("/api/v1/messenger/webhook", json=payload)
    second = client.post("/api/v1/messenger/webhook", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user_id,
        CreditTransaction.action == "capture",
    ).count()
    assert capture_count == 1
    assert outgoing_messages == [
        ("psid-linked-2", "text", "測試回答（messenger）"),
        (
            "psid-linked-2",
            "text",
            "你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
        ("psid-linked-2", "quick_replies", "請直接點選要追問的延伸問題："),
    ]


def test_webhook_post_message_event_strips_followup_text_from_answer(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-linked-sanitized",
        page_id="page-linked-sanitized",
        balance=2,
    )
    monkeypatch.setattr(
        "app.ask_service._generate_answer_from_openai_file_search",
        lambda _: (
            "主回答第一段。\n\n如果你願意，我可以再幫你看看：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
            "rag",
            ["延伸 A", "延伸 B", "延伸 C"],
        ),
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-sanitized",
                "time": 1700000201,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-sanitized"},
                        "recipient": {"id": "page-linked-sanitized"},
                        "timestamp": 1700000201,
                        "message": {
                            "mid": "m_linked_sanitized",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert outgoing_messages == [
        ("psid-linked-sanitized", "text", "主回答第一段。"),
        (
            "psid-linked-sanitized",
            "text",
            "你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
        ("psid-linked-sanitized", "quick_replies", "請直接點選要追問的延伸問題："),
    ]


def test_webhook_post_message_event_followup_quick_replies_use_fixed_titles(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-linked-titles",
        page_id="page-linked-titles",
        balance=2,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-titles",
                "time": 1700000202,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-titles"},
                        "recipient": {"id": "page-linked-titles"},
                        "timestamp": 1700000202,
                        "message": {
                            "mid": "m_linked_titles",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    _, quick_reply_outgoing = captured_outgoing[2]
    assert quick_reply_outgoing.kind == "quick_replies"
    assert [item.title for item in quick_reply_outgoing.quick_replies] == [
        "延伸問題一",
        "延伸問題二",
        "延伸問題三",
    ]


def test_webhook_post_message_event_with_two_followups_lists_only_existing_items(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-linked-two-followups",
        page_id="page-linked-two-followups",
        balance=2,
    )
    monkeypatch.setattr(
        "app.ask_service._generate_answer_from_openai_file_search",
        lambda _: ("雙延伸回答", "rag", ["延伸 1", "延伸 2"]),
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-two-followups",
                "time": 1700000203,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-two-followups"},
                        "recipient": {"id": "page-linked-two-followups"},
                        "timestamp": 1700000203,
                        "message": {
                            "mid": "m_linked_two_followups",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    _, followup_text_outgoing = captured_outgoing[1]
    _, quick_reply_outgoing = captured_outgoing[2]
    assert followup_text_outgoing.text == "你也可以選擇以下延伸問題：\n1. 延伸 1\n2. 延伸 2"
    assert [item.title for item in quick_reply_outgoing.quick_replies] == [
        "延伸問題一",
        "延伸問題二",
    ]


def test_webhook_post_message_event_with_insufficient_credit(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-linked-3",
        page_id="page-linked-3",
        balance=0,
    )
    user_id = user.id
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-3",
                "time": 1700000300,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-3"},
                        "recipient": {"id": "page-linked-3"},
                        "timestamp": 1700000300,
                        "message": {
                            "mid": "m_linked_3",
                            "text": "我還可以問嗎",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 0

    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user_id,
        CreditTransaction.action == "capture",
    ).count()
    assert capture_count == 0


def test_webhook_post_message_event_with_insufficient_credit_returns_topup_button(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-linked-topup",
        page_id="page-linked-topup",
        balance=0,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-topup",
                "time": 1700000301,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-topup"},
                        "recipient": {"id": "page-linked-topup"},
                        "timestamp": 1700000301,
                        "message": {
                            "mid": "m_linked_topup",
                            "text": "我還可以問嗎",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-linked-topup"
    assert outgoing.kind == "button_template"
    assert outgoing.text == "目前點數不足，請先購點後再提問。"
    assert outgoing.buttons[0] == {
        "type": "web_url",
        "title": "前往購點",
        "url": "https://frontend.example.com/wallet?from=messenger-insufficient-credit",
    }


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


def test_webhook_post_quick_reply_for_unlinked_user_returns_linking_reply(
    client: TestClient,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-unlinked-qr",
                "time": 1700002050,
                "messaging": [
                    {
                        "sender": {"id": "psid-unlinked-qr"},
                        "recipient": {"id": "page-unlinked-qr"},
                        "timestamp": 1700002050,
                        "message": {
                            "mid": "m_unlinked_qr",
                            "text": "pick",
                            "quick_reply": {
                                "payload": "FOLLOWUP:12345678-1234-1234-1234-123456789012"
                            },
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert outgoing_messages[-1] == (
        "psid-unlinked-qr",
        "button_template",
        "已收到你的訊息。請先完成網站登入與帳號綁定後再提問。",
    )


def test_webhook_post_quick_reply_for_linked_user_runs_followup_flow(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-1",
        page_id="page-followup-1",
        balance=2,
    )
    user_id = user.id
    followup = _create_pending_followup(db_session, user_id=user_id, content="請延伸分析")
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-1",
                "time": 1700002100,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-1"},
                        "recipient": {"id": "page-followup-1"},
                        "timestamp": 1700002100,
                        "message": {
                            "mid": "m_followup_1",
                            "text": "請繼續",
                            "quick_reply": {"payload": f"FOLLOWUP:{followup.id}"},
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    stored_followup = db_session.scalar(select(Followup).where(Followup.id == followup.id))
    assert stored_followup is not None
    assert stored_followup.status == "used"
    assert stored_followup.used_question_id is not None

    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user_id,
        CreditTransaction.action == "capture",
    ).count()
    assert capture_count == 1
    assert outgoing_messages[0] == ("psid-followup-1", "text", "測試回答（messenger）")
    assert outgoing_messages[1] == (
        "psid-followup-1",
        "text",
        "你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
    )
    assert outgoing_messages[2] == (
        "psid-followup-1",
        "quick_replies",
        "請直接點選要追問的延伸問題：",
    )


def test_webhook_post_quick_reply_with_same_followup_is_not_double_charged(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-2",
        page_id="page-followup-2",
        balance=2,
    )
    user_id = user.id
    followup = _create_pending_followup(db_session, user_id=user_id, content="再問一次")
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-2",
                "time": 1700002200,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-2"},
                        "recipient": {"id": "page-followup-2"},
                        "timestamp": 1700002200,
                        "message": {
                            "mid": "m_followup_2",
                            "text": "再問一次",
                            "quick_reply": {"payload": f"FOLLOWUP:{followup.id}"},
                        },
                    }
                ],
            }
        ],
    }

    first = client.post("/api/v1/messenger/webhook", json=payload)
    second = client.post("/api/v1/messenger/webhook", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1

    capture_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user_id,
        CreditTransaction.action == "capture",
    ).count()
    assert capture_count == 1
    assert outgoing_messages[-1] == (
        "psid-followup-2",
        "text",
        "這個延伸問題已失效，請重新提問。",
    )


def test_webhook_post_quick_reply_with_invalid_payload_returns_fallback(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-invalid-qr",
        page_id="page-invalid-qr",
        balance=1,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-invalid-qr",
                "time": 1700002300,
                "messaging": [
                    {
                        "sender": {"id": "psid-invalid-qr"},
                        "recipient": {"id": "page-invalid-qr"},
                        "timestamp": 1700002300,
                        "message": {
                            "mid": "m_invalid_qr",
                            "text": "bad payload",
                            "quick_reply": {"payload": "QR_PAYLOAD"},
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert outgoing_messages[-1] == (
        "psid-invalid-qr",
        "text",
        "這個延伸問題目前無法使用，請重新選擇或重新提問。",
    )


def test_webhook_post_quick_reply_with_insufficient_credit_restores_followup(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-3",
        page_id="page-followup-3",
        balance=0,
    )
    user_id = user.id
    followup = _create_pending_followup(db_session, user_id=user_id, content="沒點數的追問")
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-3",
                "time": 1700002400,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-3"},
                        "recipient": {"id": "page-followup-3"},
                        "timestamp": 1700002400,
                        "message": {
                            "mid": "m_followup_3",
                            "text": "沒點數",
                            "quick_reply": {"payload": f"FOLLOWUP:{followup.id}"},
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 0

    stored_followup = db_session.scalar(select(Followup).where(Followup.id == followup.id))
    assert stored_followup is not None
    assert stored_followup.status == "pending"
    assert stored_followup.used_question_id is None
    psid, outgoing = captured_outgoing[-1]
    assert psid == "psid-followup-3"
    assert outgoing.kind == "button_template"
    assert outgoing.text == "目前點數不足，請先購點後再提問。"
    assert outgoing.buttons == [
        {
            "type": "web_url",
            "title": "前往購點",
            "url": "https://frontend.example.com/wallet?from=messenger-insufficient-credit",
        },
        {
            "type": "postback",
            "title": "購買完成，重新顯示延伸問題",
            "payload": f"RESHOW_FOLLOWUPS:{followup.id}",
        },
    ]


def test_webhook_post_postback_reshows_pending_followups_after_topup(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-reshow",
        page_id="page-followup-reshow",
        balance=3,
    )
    user_id = user.id
    first_followup = _create_pending_followup(
        db_session,
        user_id=user_id,
        content="重新顯示的延伸問題一",
    )
    second_followup = Followup(
        question_id=first_followup.question_id,
        user_id=user_id,
        content="重新顯示的延伸問題二",
        origin_request_id=str(uuid.uuid4()),
        status="pending",
    )
    db_session.add(second_followup)
    db_session.commit()
    db_session.refresh(second_followup)

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-reshow",
                "time": 1700002450,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-reshow"},
                        "recipient": {"id": "page-followup-reshow"},
                        "timestamp": 1700002450,
                        "postback": {
                            "payload": f"RESHOW_FOLLOWUPS:{first_followup.id}",
                            "title": "購買完成，重新顯示延伸問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 2
    _, followup_text_outgoing = captured_outgoing[0]
    _, quick_reply_outgoing = captured_outgoing[1]
    assert followup_text_outgoing.kind == "text"
    assert (
        followup_text_outgoing.text
        == "你也可以選擇以下延伸問題：\n1. 重新顯示的延伸問題一\n2. 重新顯示的延伸問題二"
    )
    assert quick_reply_outgoing.kind == "quick_replies"
    assert [item.title for item in quick_reply_outgoing.quick_replies] == [
        "延伸問題一",
        "延伸問題二",
    ]
    assert [item.payload for item in quick_reply_outgoing.quick_replies] == [
        f"FOLLOWUP:{first_followup.id}",
        f"FOLLOWUP:{second_followup.id}",
    ]


def test_webhook_post_postback_reshow_returns_fallback_when_no_pending_followups(
    client: TestClient,
    db_session: Session,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-reshow-none",
        page_id="page-followup-reshow-none",
        balance=3,
    )
    used_followup = _create_pending_followup(
        db_session,
        user_id=user.id,
        content="已用掉的延伸問題",
    )
    used_followup.status = "used"
    used_followup.used_at = datetime.now(UTC)
    db_session.add(used_followup)
    db_session.commit()

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-reshow-none",
                "time": 1700002451,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-reshow-none"},
                        "recipient": {"id": "page-followup-reshow-none"},
                        "timestamp": 1700002451,
                        "postback": {
                            "payload": f"RESHOW_FOLLOWUPS:{used_followup.id}",
                            "title": "購買完成，重新顯示延伸問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert outgoing_messages[-1] == (
        "psid-followup-reshow-none",
        "text",
        "目前沒有可重新顯示的延伸問題，請重新提問。",
    )


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


def test_messenger_link_endpoint_links_identity_to_verified_user(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_verified_user_with_token(db_session)
    user_id = user.id
    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-1",
        page_id="page-link-1",
        status="unlinked",
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    link_token = create_messenger_link_token(
        psid="psid-link-1",
        page_id="page-link-1",
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.post(
        "/api/v1/messenger/link",
        headers={"Authorization": f"Bearer {token}"},
        json={"token": link_token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "linked"
    db_session.refresh(identity)
    assert identity.user_id == user_id
    assert identity.status == "linked"
    assert identity.linked_at is not None


def test_messenger_link_endpoint_is_idempotent_for_same_user(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_verified_user_with_token(db_session)
    user_id = user.id
    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-2",
        page_id="page-link-2",
        status="unlinked",
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    link_token = create_messenger_link_token(
        psid="psid-link-2",
        page_id="page-link-2",
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    first = client.post(
        "/api/v1/messenger/link",
        headers={"Authorization": f"Bearer {token}"},
        json={"token": link_token},
    )
    second = client.post(
        "/api/v1/messenger/link",
        headers={"Authorization": f"Bearer {token}"},
        json={"token": link_token},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    db_session.refresh(identity)
    assert identity.user_id == user_id
    assert identity.status == "linked"


def test_messenger_link_endpoint_rejects_other_user_link_takeover(
    client: TestClient,
    db_session: Session,
) -> None:
    linked_user, _ = _create_verified_user_with_token(db_session)
    other_user, token = _create_verified_user_with_token(db_session)
    linked_user_id = linked_user.id
    other_user_id = other_user.id
    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-3",
        page_id="page-link-3",
        user_id=linked_user_id,
        status="linked",
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    link_token = create_messenger_link_token(
        psid="psid-link-3",
        page_id="page-link-3",
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.post(
        "/api/v1/messenger/link",
        headers={"Authorization": f"Bearer {token}"},
        json={"token": link_token},
    )

    assert other_user_id != linked_user_id
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MESSENGER_IDENTITY_ALREADY_LINKED"


def test_messenger_link_endpoint_rejects_invalid_token(
    client: TestClient,
    db_session: Session,
) -> None:
    _, token = _create_verified_user_with_token(db_session)

    response = client.post(
        "/api/v1/messenger/link",
        headers={"Authorization": f"Bearer {token}"},
        json={"token": "bad-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MESSENGER_LINK_TOKEN_INVALID"


def test_webhook_outbound_failure_returns_accepted_instead_of_500(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-outbound-fail",
        page_id="page-outbound-fail",
        balance=2,
    )
    user_id = user.id
    monkeypatch.setattr(settings, "messenger_outbound_mode", "meta_graph")
    monkeypatch.setattr(settings, "meta_page_access_token", "page-token")

    def _raise_send_error(self, *, psid: str, text: str) -> None:  # noqa: ANN001
        raise MessengerClientError(f"send failed for {psid}: {text}")

    monkeypatch.setattr(
        "app.messenger.client.MetaGraphMessengerClient.send_text",
        _raise_send_error,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-outbound-fail",
                "time": 1700002600,
                "messaging": [
                    {
                        "sender": {"id": "psid-outbound-fail"},
                        "recipient": {"id": "page-outbound-fail"},
                        "timestamp": 1700002600,
                        "message": {
                            "mid": "m_outbound_fail",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "processed": 1}

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
    assert wallet is not None
    assert wallet.balance == 1
