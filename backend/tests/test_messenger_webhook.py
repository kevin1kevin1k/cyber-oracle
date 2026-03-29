import hashlib
import os
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from fastapi import HTTPException, status
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
from app.messenger.service import build_default_persistent_menu
from app.models.answer import Answer
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet
from app.models.followup import Followup
from app.models.messenger_identity import MessengerIdentity
from app.models.messenger_pending_ask import MessengerPendingAsk
from app.models.order import Order
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
        MessengerPendingAsk.__table__,
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
        session.query(MessengerPendingAsk).delete()
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
    profile_complete: bool = True,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
        full_name="王小明" if profile_complete else None,
        mother_name="林淑芬" if profile_complete else None,
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


@pytest.fixture
def processing_feedback_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []

    def _capture_start(*, client, psid: str) -> None:  # noqa: ANN001
        events.append(("start", psid))

    def _capture_stop(*, client, psid: str) -> None:  # noqa: ANN001
        events.append(("stop", psid))

    monkeypatch.setattr("app.messenger.routes._emit_processing_feedback", _capture_start)
    monkeypatch.setattr("app.messenger.routes._stop_processing_feedback", _capture_stop)
    return events


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
    assert (
        outgoing.text
        == "已收到你的訊息。請先點擊下方按鈕完成 Messenger 綁定，之後就能直接提問。"
    )
    assert outgoing.buttons[0]["title"] == "開始綁定"
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


def test_webhook_post_message_event_for_incomplete_profile_returns_settings_and_replay_buttons(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-linked-profile-missing",
        page_id="page-linked-profile-missing",
        balance=2,
        profile_complete=False,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-profile-missing",
                "time": 1700000101,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-profile-missing"},
                        "recipient": {"id": "page-linked-profile-missing"},
                        "timestamp": 1700000101,
                        "message": {
                            "mid": "m_linked_profile_missing",
                            "text": "請幫我分析今天運勢",
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
    assert psid == "psid-linked-profile-missing"
    assert outgoing.kind == "button_template"
    assert (
        outgoing.text
        == "開始提問前，請先補上你的姓名與母親姓名。完成後就能直接在 Messenger 提問。"
    )
    assert outgoing.buttons[0]["title"] == "前往設定"
    assert "next=%2F%3Ffrom%3Dmessenger-profile-required" in outgoing.buttons[0]["url"]
    pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(
            MessengerPendingAsk.user_id == user.id,
            MessengerPendingAsk.status == "pending",
        )
    )
    assert pending_ask is not None
    assert pending_ask.question_text == "請幫我分析今天運勢"
    assert pending_ask.lang == "zh"
    assert pending_ask.mode == "analysis"
    assert outgoing.buttons[1] == {
        "type": "postback",
        "title": "設定完成，重新送出剛剛的問題",
        "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
    }


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
        ("psid-linked-2", "text", "本次已扣 1 點，目前剩餘 1 點。"),
        (
            "psid-linked-2",
            "quick_replies",
            "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
    ]


def test_webhook_post_message_event_emits_processing_feedback_before_answer(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    processing_feedback_events: list[tuple[str, str]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-linked-feedback",
        page_id="page-linked-feedback",
        balance=2,
    )
    events: list[tuple[str, str, str]] = []

    def _capture_dispatch(*, client, psid: str, outgoing) -> None:  # noqa: ANN001
        events.append((psid, outgoing.kind, outgoing.text))

    monkeypatch.setattr("app.messenger.routes.dispatch_outgoing_message", _capture_dispatch)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-feedback",
                "time": 1700000204,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-feedback"},
                        "recipient": {"id": "page-linked-feedback"},
                        "timestamp": 1700000204,
                        "message": {
                            "mid": "m_linked_feedback",
                            "text": "請幫我分析今天運勢",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert processing_feedback_events == [
        ("start", "psid-linked-feedback"),
        ("stop", "psid-linked-feedback"),
    ]
    assert events == [
        ("psid-linked-feedback", "text", "本次已扣 1 點，目前剩餘 1 點。"),
        (
            "psid-linked-feedback",
            "quick_replies",
            "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
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
        ("psid-linked-sanitized", "text", "本次已扣 1 點，目前剩餘 1 點。"),
        (
            "psid-linked-sanitized",
            "quick_replies",
            "主回答第一段。\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
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
    _, balance_outgoing = captured_outgoing[0]
    assert balance_outgoing.kind == "text"
    assert balance_outgoing.text == "本次已扣 1 點，目前剩餘 1 點。"
    _, quick_reply_outgoing = captured_outgoing[1]
    assert quick_reply_outgoing.kind == "quick_replies"
    assert quick_reply_outgoing.text.startswith(
        "測試回答（messenger）\n\n你也可以選擇以下延伸問題："
    )
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
    _, balance_outgoing = captured_outgoing[0]
    assert balance_outgoing.kind == "text"
    assert balance_outgoing.text == "本次已扣 1 點，目前剩餘 1 點。"
    _, quick_reply_outgoing = captured_outgoing[1]
    assert (
        quick_reply_outgoing.text
        == "雙延伸回答\n\n你也可以選擇以下延伸問題：\n1. 延伸 1\n2. 延伸 2"
    )
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
    user = _create_linked_messenger_user(
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
    pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(
            MessengerPendingAsk.user_id == user.id,
            MessengerPendingAsk.status == "pending",
        )
    )
    assert pending_ask is not None
    assert pending_ask.question_text == "我還可以問嗎"
    assert pending_ask.lang == "zh"
    assert pending_ask.mode == "analysis"
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "前往購點"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2Fwallet%3Ffrom%3Dmessenger-insufficient-credit" in outgoing.buttons[0]["url"]
    assert outgoing.buttons[1] == {
        "type": "postback",
        "title": "購買完成，重新送出剛剛的問題",
        "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
    }


def test_webhook_post_message_event_with_insufficient_credit_reuses_existing_pending_ask(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-linked-topup-replay",
        page_id="page-linked-topup-replay",
        balance=0,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-linked-topup-replay",
            MessengerIdentity.page_id == "page-linked-topup-replay",
        )
    )
    assert identity is not None
    existing_pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="我還可以問嗎",
        lang="zh",
        mode="analysis",
        idempotency_key="msg:"
        + hashlib.sha256(b"psid-linked-topup-replay:m_linked_topup").hexdigest()[:40],
        status="pending",
    )
    db_session.add(existing_pending_ask)
    db_session.commit()
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-linked-topup-replay",
                "time": 1700000301,
                "messaging": [
                    {
                        "sender": {"id": "psid-linked-topup-replay"},
                        "recipient": {"id": "page-linked-topup-replay"},
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
    pending_asks = db_session.scalars(
        select(MessengerPendingAsk).where(MessengerPendingAsk.user_id == user.id)
    ).all()
    assert [item.id for item in pending_asks] == [existing_pending_ask.id]
    _, outgoing = captured_outgoing[-1]
    assert outgoing.buttons[-1] == {
        "type": "postback",
        "title": "購買完成，重新送出剛剛的問題",
        "payload": f"REPLAY_PENDING_ASK:{existing_pending_ask.id}",
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


def test_webhook_post_postback_show_balance_for_linked_user(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-balance-1",
        page_id="page-balance-1",
        balance=3,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-balance-1",
                "time": 1700001001,
                "messaging": [
                    {
                        "sender": {"id": "psid-balance-1"},
                        "recipient": {"id": "page-balance-1"},
                        "timestamp": 1700001001,
                        "postback": {"payload": "SHOW_BALANCE"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-balance-1"
    assert outgoing.kind == "text"
    assert outgoing.text == "目前剩餘 3 點。"


def test_webhook_post_postback_get_started_for_linked_user(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-get-started-linked",
        page_id="page-get-started-linked",
        balance=2,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-get-started-linked",
                "time": 1700001004,
                "messaging": [
                    {
                        "sender": {"id": "psid-get-started-linked"},
                        "recipient": {"id": "page-get-started-linked"},
                        "timestamp": 1700001004,
                        "postback": {"payload": "GET_STARTED"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-get-started-linked"
    assert outgoing.kind == "text"
    assert (
        outgoing.text
        == "已開啟 Messenger 助手。你可以直接提問，或使用選單查看點數與設定。"
    )


def test_webhook_post_postback_get_started_for_unlinked_user_returns_onboarding_button(
    client: TestClient,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-get-started-unlinked",
                "time": 1700001005,
                "messaging": [
                    {
                        "sender": {"id": "psid-get-started-unlinked"},
                        "recipient": {"id": "page-get-started-unlinked"},
                        "timestamp": 1700001005,
                        "postback": {"payload": "GET_STARTED"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-get-started-unlinked"
    assert outgoing.kind == "button_template"
    assert (
        outgoing.text
        == "先完成 Messenger 綁定與固定資料設定。目前會先提供 50 點測試用點數，每次提問扣 1 點，"
        "之後就能直接回 Messenger 提問。"
    )
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "前往設定"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2F%3Ffrom%3Dmessenger-get-started" in outgoing.buttons[0]["url"]


def test_webhook_post_postback_get_started_for_linked_user_without_profile(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-get-started-no-profile",
        page_id="page-get-started-no-profile",
        balance=2,
        profile_complete=False,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-get-started-no-profile",
                "time": 1700001008,
                "messaging": [
                    {
                        "sender": {"id": "psid-get-started-no-profile"},
                        "recipient": {"id": "page-get-started-no-profile"},
                        "timestamp": 1700001008,
                        "postback": {"payload": "GET_STARTED"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    psid, outgoing = captured_outgoing[0]
    assert psid == "psid-get-started-no-profile"
    assert outgoing.kind == "button_template"
    assert (
        outgoing.text
        == "先完成 Messenger 綁定與固定資料設定。目前會先提供 50 點測試用點數，每次提問扣 1 點，"
        "之後就能直接回 Messenger 提問。"
    )
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "前往設定"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2F%3Ffrom%3Dmessenger-get-started" in outgoing.buttons[0]["url"]


def test_webhook_post_postback_show_balance_for_zero_balance_returns_topup(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-balance-0",
        page_id="page-balance-0",
        balance=0,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-balance-0",
                "time": 1700001002,
                "messaging": [
                    {
                        "sender": {"id": "psid-balance-0"},
                        "recipient": {"id": "page-balance-0"},
                        "timestamp": 1700001002,
                        "postback": {"payload": "SHOW_BALANCE"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 2
    _, balance_outgoing = captured_outgoing[0]
    _, topup_outgoing = captured_outgoing[1]
    assert balance_outgoing.kind == "text"
    assert balance_outgoing.text == "目前剩餘 0 點。"
    assert topup_outgoing.kind == "button_template"
    assert topup_outgoing.buttons[0]["type"] == "web_url"
    assert topup_outgoing.buttons[0]["title"] == "前往購點"
    assert topup_outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert (
        "next=%2Fwallet%3Ffrom%3Dmessenger-insufficient-credit"
        in topup_outgoing.buttons[0]["url"]
    )


def test_webhook_post_postback_show_balance_does_not_emit_processing_feedback(
    client: TestClient,
    db_session: Session,
    processing_feedback_events: list[tuple[str, str]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-balance-no-feedback",
        page_id="page-balance-no-feedback",
        balance=3,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-balance-no-feedback",
                "time": 1700001009,
                "messaging": [
                    {
                        "sender": {"id": "psid-balance-no-feedback"},
                        "recipient": {"id": "page-balance-no-feedback"},
                        "timestamp": 1700001009,
                        "postback": {"payload": "SHOW_BALANCE"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert processing_feedback_events == []


def test_webhook_post_postback_show_balance_for_unlinked_user_returns_linking(
    client: TestClient,
    outgoing_messages: list[tuple[str, str, str]],
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-balance-unlinked",
                "time": 1700001003,
                "messaging": [
                    {
                        "sender": {"id": "psid-balance-unlinked"},
                        "recipient": {"id": "page-balance-unlinked"},
                        "timestamp": 1700001003,
                        "postback": {"payload": "SHOW_BALANCE"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert outgoing_messages[-1] == (
        "psid-balance-unlinked",
        "button_template",
        "已收到你的訊息。請先點擊下方按鈕完成 Messenger 綁定，之後就能直接提問。",
    )


def test_webhook_post_postback_open_settings_returns_bridge_button(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-open-settings",
        page_id="page-open-settings",
        balance=3,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-open-settings",
                "time": 1700001006,
                "messaging": [
                    {
                        "sender": {"id": "psid-open-settings"},
                        "recipient": {"id": "page-open-settings"},
                        "timestamp": 1700001006,
                        "postback": {"payload": "OPEN_SETTINGS"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    _, outgoing = captured_outgoing[0]
    assert outgoing.kind == "button_template"
    assert outgoing.text == "請點擊下方按鈕開啟設定中心。"
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "開啟設定中心"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2F" in outgoing.buttons[0]["url"]


def test_webhook_post_postback_legacy_open_history_returns_settings_bridge_button(
    client: TestClient,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-open-history",
                "time": 1700001007,
                "messaging": [
                    {
                        "sender": {"id": "psid-open-history"},
                        "recipient": {"id": "page-open-history"},
                        "timestamp": 1700001007,
                        "postback": {"payload": "OPEN_HISTORY"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    _, outgoing = captured_outgoing[0]
    assert outgoing.kind == "button_template"
    assert outgoing.text == "請點擊下方按鈕開啟設定中心。"
    assert outgoing.buttons[0]["title"] == "開啟設定中心"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=" not in outgoing.buttons[0]["url"]


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
        "已收到你的訊息。請先點擊下方按鈕完成 Messenger 綁定，之後就能直接提問。",
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
    assert outgoing_messages[0] == (
        "psid-followup-1",
        "text",
        "本次已扣 1 點，目前剩餘 1 點。",
    )
    assert outgoing_messages[1] == (
        "psid-followup-1",
        "quick_replies",
        "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
    )


def test_webhook_post_quick_reply_emits_processing_feedback_before_answer(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    processing_feedback_events: list[tuple[str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-feedback",
        page_id="page-followup-feedback",
        balance=2,
    )
    followup = _create_pending_followup(db_session, user_id=user.id, content="請延伸分析")
    events: list[tuple[str, str, str]] = []

    def _capture_dispatch(*, client, psid: str, outgoing) -> None:  # noqa: ANN001
        events.append((psid, outgoing.kind, outgoing.text))

    monkeypatch.setattr("app.messenger.routes.dispatch_outgoing_message", _capture_dispatch)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-feedback",
                "time": 1700002101,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-feedback"},
                        "recipient": {"id": "page-followup-feedback"},
                        "timestamp": 1700002101,
                        "message": {
                            "mid": "m_followup_feedback",
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
    assert processing_feedback_events == [
        ("start", "psid-followup-feedback"),
        ("stop", "psid-followup-feedback"),
    ]
    assert events == [
        ("psid-followup-feedback", "text", "本次已扣 1 點，目前剩餘 1 點。"),
        (
            "psid-followup-feedback",
            "quick_replies",
            "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
    ]


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
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "前往購點"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2Fwallet%3Ffrom%3Dmessenger-insufficient-credit" in outgoing.buttons[0]["url"]
    assert outgoing.buttons[1] == {
        "type": "postback",
        "title": "購買完成，重新顯示延伸問題",
        "payload": f"RESHOW_FOLLOWUPS:{followup.id}",
    }


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
    assert len(captured_outgoing) == 1
    _, quick_reply_outgoing = captured_outgoing[0]
    assert quick_reply_outgoing.kind == "quick_replies"
    assert (
        quick_reply_outgoing.text
        == "你也可以選擇以下延伸問題：\n1. 重新顯示的延伸問題一\n2. 重新顯示的延伸問題二"
    )
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


def test_webhook_post_postback_replays_pending_ask_after_topup(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-replay",
        page_id="page-pending-ask-replay",
        balance=3,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-pending-ask-replay",
            MessengerIdentity.page_id == "page-pending-ask-replay",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="剛剛那題再問一次",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-replay",
                "time": 1700002500,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-replay"},
                        "recipient": {"id": "page-pending-ask-replay"},
                        "timestamp": 1700002500,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "購買完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    stored_pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
    )
    assert stored_pending_ask is not None
    assert stored_pending_ask.status == "used"
    assert stored_pending_ask.used_question_id is not None
    assert len(captured_outgoing) == 2
    psid, balance_outgoing = captured_outgoing[0]
    assert psid == "psid-pending-ask-replay"
    assert balance_outgoing.kind == "text"
    assert balance_outgoing.text == "本次已扣 1 點，目前剩餘 2 點。"
    _, outgoing = captured_outgoing[1]
    assert outgoing.kind == "quick_replies"
    assert (
        outgoing.text
        == "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C"
    )


def test_webhook_post_postback_replay_pending_ask_emits_processing_feedback(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    processing_feedback_events: list[tuple[str, str]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-feedback",
        page_id="page-pending-ask-feedback",
        balance=3,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-pending-ask-feedback",
            MessengerIdentity.page_id == "page-pending-ask-feedback",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="剛剛那題再問一次",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()
    events: list[tuple[str, str, str]] = []

    def _capture_dispatch(*, client, psid: str, outgoing) -> None:  # noqa: ANN001
        events.append((psid, outgoing.kind, outgoing.text))

    monkeypatch.setattr("app.messenger.routes.dispatch_outgoing_message", _capture_dispatch)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-feedback",
                "time": 1700002501,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-feedback"},
                        "recipient": {"id": "page-pending-ask-feedback"},
                        "timestamp": 1700002501,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "購買完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert processing_feedback_events == [
        ("start", "psid-pending-ask-feedback"),
        ("stop", "psid-pending-ask-feedback"),
    ]
    assert events == [
        ("psid-pending-ask-feedback", "text", "本次已扣 1 點，目前剩餘 2 點。"),
        (
            "psid-pending-ask-feedback",
            "quick_replies",
            "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C",
        ),
    ]


def test_webhook_post_postback_replay_pending_ask_without_credit_returns_topup_again(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-zero",
        page_id="page-pending-ask-zero",
        balance=0,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-pending-ask-zero",
            MessengerIdentity.page_id == "page-pending-ask-zero",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="沒點數時重問",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-zero",
                "time": 1700002600,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-zero"},
                        "recipient": {"id": "page-pending-ask-zero"},
                        "timestamp": 1700002600,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "購買完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    stored_pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
    )
    assert stored_pending_ask is not None
    assert stored_pending_ask.status == "pending"
    _, outgoing = captured_outgoing[-1]
    assert outgoing.kind == "button_template"
    assert outgoing.buttons[0]["type"] == "web_url"
    assert outgoing.buttons[0]["title"] == "前往購點"
    assert outgoing.buttons[0]["url"].startswith(
        "https://frontend.example.com/messenger/link?token="
    )
    assert "next=%2Fwallet%3Ffrom%3Dmessenger-insufficient-credit" in outgoing.buttons[0]["url"]
    assert outgoing.buttons[1] == {
        "type": "postback",
        "title": "購買完成，重新送出剛剛的問題",
        "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
    }


def test_webhook_post_postback_replay_pending_ask_without_profile_returns_settings_again(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-profile-missing",
        page_id="page-pending-ask-profile-missing",
        balance=3,
        profile_complete=False,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-pending-ask-profile-missing",
            MessengerIdentity.page_id == "page-pending-ask-profile-missing",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="請再幫我看一次",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-profile-missing",
                "time": 1700002650,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-profile-missing"},
                        "recipient": {"id": "page-pending-ask-profile-missing"},
                        "timestamp": 1700002650,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "設定完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    stored_pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
    )
    assert stored_pending_ask is not None
    assert stored_pending_ask.status == "pending"
    assert stored_pending_ask.used_question_id is None
    _, outgoing = captured_outgoing[-1]
    assert outgoing.kind == "button_template"
    assert (
        outgoing.text
        == "開始提問前，請先補上你的姓名與母親姓名。完成後就能直接在 Messenger 提問。"
    )
    assert outgoing.buttons[0]["title"] == "前往設定"
    assert "next=%2F%3Ffrom%3Dmessenger-profile-required" in outgoing.buttons[0]["url"]
    assert outgoing.buttons[1] == {
        "type": "postback",
        "title": "設定完成，重新送出剛剛的問題",
        "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
    }


def test_webhook_post_postback_replays_pending_ask_after_profile_completed(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-profile-fixed",
        page_id="page-pending-ask-profile-fixed",
        balance=3,
        profile_complete=False,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-pending-ask-profile-fixed",
            MessengerIdentity.page_id == "page-pending-ask-profile-fixed",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="補完資料後重問",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()

    user.full_name = "王小明"
    user.mother_name = "林淑芬"
    db_session.add(user)
    db_session.commit()

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-profile-fixed",
                "time": 1700002651,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-profile-fixed"},
                        "recipient": {"id": "page-pending-ask-profile-fixed"},
                        "timestamp": 1700002651,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "設定完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    stored_pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
    )
    assert stored_pending_ask is not None
    assert stored_pending_ask.status == "used"
    assert stored_pending_ask.used_question_id is not None
    _, balance_outgoing = captured_outgoing[0]
    assert balance_outgoing.kind == "text"
    assert balance_outgoing.text == "本次已扣 1 點，目前剩餘 2 點。"
    _, outgoing = captured_outgoing[1]
    assert outgoing.kind == "quick_replies"
    assert (
        outgoing.text
        == "測試回答（messenger）\n\n你也可以選擇以下延伸問題：\n1. 延伸 A\n2. 延伸 B\n3. 延伸 C"
    )


def test_webhook_post_message_event_returns_configured_ask_failure_message(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-ask-config",
        page_id="page-ask-config",
        balance=3,
    )

    def _raise_config_error(**kwargs):  # noqa: ANN003, ANN001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "OPENAI_NOT_CONFIGURED", "message": "OPENAI_API_KEY is required"},
        )

    monkeypatch.setattr("app.messenger.service.execute_ask_for_user", _raise_config_error)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-ask-config",
                "time": 1700002697,
                "messaging": [
                    {
                        "sender": {"id": "psid-ask-config"},
                        "recipient": {"id": "page-ask-config"},
                        "timestamp": 1700002697,
                        "message": {"mid": "m_ask_config", "text": "請幫我看看"},
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    _, outgoing = captured_outgoing[-1]
    assert outgoing.kind == "text"
    assert outgoing.text == "目前系統設定尚未完成，請稍後再試。"


def test_webhook_post_quick_reply_returns_upstream_followup_failure_message(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-followup-upstream",
        page_id="page-followup-upstream",
        balance=3,
    )
    followup = _create_pending_followup(
        db_session,
        user_id=user.id,
        content="延伸追問",
    )

    def _raise_upstream_error(**kwargs):  # noqa: ANN003, ANN001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "OPENAI_ASK_FAILED", "message": "OpenAI ask request failed"},
        )

    monkeypatch.setattr("app.messenger.service.execute_followup_for_user", _raise_upstream_error)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-followup-upstream",
                "time": 1700002698,
                "messaging": [
                    {
                        "sender": {"id": "psid-followup-upstream"},
                        "recipient": {"id": "page-followup-upstream"},
                        "timestamp": 1700002698,
                        "message": {
                            "mid": "m_followup_upstream",
                            "text": "追問",
                            "quick_reply": {"payload": f"FOLLOWUP:{followup.id}"},
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    _, outgoing = captured_outgoing[-1]
    assert outgoing.kind == "text"
    assert outgoing.text == "目前延伸問題服務暫時異常，請稍後再試。"


def test_webhook_post_postback_replay_pending_ask_returns_configured_ask_failure_message(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_linked_messenger_user(
        db_session,
        psid="psid-replay-config",
        page_id="page-replay-config",
        balance=3,
    )
    identity = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-replay-config",
            MessengerIdentity.page_id == "page-replay-config",
        )
    )
    assert identity is not None
    pending_ask = MessengerPendingAsk(
        user_id=user.id,
        messenger_identity_id=identity.id,
        question_text="重送這題",
        lang="zh",
        mode="analysis",
        idempotency_key=f"msg:{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(pending_ask)
    db_session.commit()

    def _raise_config_error(**kwargs):  # noqa: ANN003, ANN001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "OPENAI_NOT_CONFIGURED", "message": "OPENAI_API_KEY is required"},
        )

    monkeypatch.setattr("app.messenger.service.execute_ask_for_user", _raise_config_error)
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-replay-config",
                "time": 1700002699,
                "messaging": [
                    {
                        "sender": {"id": "psid-replay-config"},
                        "recipient": {"id": "page-replay-config"},
                        "timestamp": 1700002699,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{pending_ask.id}",
                            "title": "購買完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    db_session.expire_all()
    stored_pending_ask = db_session.scalar(
        select(MessengerPendingAsk).where(MessengerPendingAsk.id == pending_ask.id)
    )
    assert stored_pending_ask is not None
    assert stored_pending_ask.status == "pending"
    _, outgoing = captured_outgoing[-1]
    assert outgoing.kind == "text"
    assert outgoing.text == "目前系統設定尚未完成，請稍後再試。"


def test_webhook_post_postback_replay_pending_ask_unavailable_returns_fallback(
    client: TestClient,
    db_session: Session,
    captured_outgoing: list[tuple[str, object]],
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-pending-ask-invalid",
        page_id="page-pending-ask-invalid",
        balance=3,
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-pending-ask-invalid",
                "time": 1700002700,
                "messaging": [
                    {
                        "sender": {"id": "psid-pending-ask-invalid"},
                        "recipient": {"id": "page-pending-ask-invalid"},
                        "timestamp": 1700002700,
                        "postback": {
                            "payload": f"REPLAY_PENDING_ASK:{uuid.uuid4()}",
                            "title": "購買完成，重新送出剛剛的問題",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    psid, outgoing = captured_outgoing[-1]
    assert psid == "psid-pending-ask-invalid"
    assert outgoing.kind == "text"
    assert outgoing.text == "這個待重送問題已失效，請重新提問。"


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


def test_messenger_link_endpoint_bootstraps_new_session_and_launch_grant(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, str]] = []

    class _FakeClient:
        def send_text(self, *, psid: str, text: str) -> None:
            sent_messages.append((psid, text))

    monkeypatch.setattr("app.messenger.routes._get_outbound_client", lambda: _FakeClient())

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
        json={"token": link_token},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "linked"
    assert payload["link_status"] == "linked_new"
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    db_session.refresh(identity)
    assert identity.user_id is not None
    assert identity.status == "linked"
    assert identity.linked_at is not None

    claims = jwt.decode(
        payload["access_token"],
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["sub"] == str(identity.user_id)
    session_record = db_session.scalar(
        select(SessionRecord).where(SessionRecord.jti == claims["jti"])
    )
    assert session_record is not None
    assert session_record.user_id == identity.user_id

    user = db_session.get(User, identity.user_id)
    assert user is not None
    assert user.channel == "messenger"
    assert user.channel_user_id == "page-link-1:psid-link-1"

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == identity.user_id))
    assert wallet is not None
    assert wallet.balance == settings.launch_credit_grant_amount

    launch_grant = db_session.scalar(
        select(CreditTransaction).where(
            CreditTransaction.user_id == identity.user_id,
            CreditTransaction.action == "grant",
            CreditTransaction.reason_code == "MESSENGER_LINK_BETA_GRANT",
        )
    )
    assert launch_grant is not None
    assert sent_messages == [
        (
            "psid-link-1",
            "你目前有 50 點測試用點數，每次問問題會扣 1 點。"
            "完成資料設定後，就可以直接在 Messenger 開始提問。",
        )
    ]

def test_messenger_link_endpoint_restores_session_for_existing_linked_identity(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, str]] = []

    class _FakeClient:
        def send_text(self, *, psid: str, text: str) -> None:
            sent_messages.append((psid, text))

    monkeypatch.setattr("app.messenger.routes._get_outbound_client", lambda: _FakeClient())

    user = User(
        id=uuid.uuid4(),
        channel="messenger",
        channel_user_id="page-link-2:psid-link-2",
    )
    db_session.add(user)
    db_session.flush()
    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-2",
        page_id="page-link-2",
        user_id=user.id,
        status="unlinked",
        is_active=True,
    )
    db_session.add(identity)
    db_session.add(CreditWallet(user_id=user.id, balance=settings.launch_credit_grant_amount))
    db_session.add(
        CreditTransaction(
            user_id=user.id,
            action="grant",
            amount=settings.launch_credit_grant_amount,
            reason_code="MESSENGER_LINK_BETA_GRANT",
            idempotency_key=f"launch-grant:{user.id}",
            request_id=str(uuid.uuid4()),
        )
    )
    db_session.commit()
    link_token = create_messenger_link_token(
        psid="psid-link-2",
        page_id="page-link-2",
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    first = client.post(
        "/api/v1/messenger/link",
        json={"token": link_token},
    )
    second = client.post(
        "/api/v1/messenger/link",
        json={"token": link_token},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["link_status"] == "session_restored"
    assert second.json()["link_status"] == "session_restored"
    db_session.refresh(identity)
    assert identity.user_id == user.id
    assert identity.status == "linked"
    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == user.id))
    assert wallet is not None
    assert wallet.balance == settings.launch_credit_grant_amount
    grant_count = db_session.query(CreditTransaction).filter(
        CreditTransaction.user_id == user.id,
        CreditTransaction.action == "grant",
        CreditTransaction.reason_code == "MESSENGER_LINK_BETA_GRANT",
    ).count()
    assert grant_count == 1
    assert sent_messages == []


def test_messenger_link_endpoint_logs_but_still_succeeds_when_intro_send_fails(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingClient:
        def send_text(self, *, psid: str, text: str) -> None:
            raise MessengerClientError("boom")

    monkeypatch.setattr("app.messenger.routes._get_outbound_client", lambda: _FailingClient())
    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-send-fail",
        page_id="page-link-send-fail",
        status="unlinked",
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    link_token = create_messenger_link_token(
        psid="psid-link-send-fail",
        page_id="page-link-send-fail",
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with caplog.at_level("WARNING"):
        response = client.post(
            "/api/v1/messenger/link",
            json={"token": link_token},
        )

    assert response.status_code == 200
    assert "Messenger new-link intro message failed" in caplog.text


def test_messenger_link_endpoint_rejects_invalid_token(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/v1/messenger/link",
        json={"token": "bad-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MESSENGER_LINK_TOKEN_INVALID"


def test_messenger_link_endpoint_rate_limit_returns_429(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "launch_credit_grant_amount", 0)

    for attempt in range(10):
        identity = MessengerIdentity(
            platform="messenger",
            psid=f"psid-link-rate-{attempt}",
            page_id=f"page-link-rate-{attempt}",
            status="unlinked",
            is_active=True,
        )
        db_session.add(identity)
        db_session.commit()
        link_token = create_messenger_link_token(
            psid=identity.psid,
            page_id=identity.page_id,
            secret_key=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        response = client.post(
            "/api/v1/messenger/link",
            json={"token": link_token},
        )
        assert response.status_code == 200

    overflow_identity = MessengerIdentity(
        platform="messenger",
        psid="psid-link-rate-overflow",
        page_id="page-link-rate-overflow",
        status="unlinked",
        is_active=True,
    )
    db_session.add(overflow_identity)
    db_session.commit()
    overflow_token = create_messenger_link_token(
        psid=overflow_identity.psid,
        page_id=overflow_identity.page_id,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    blocked = client.post(
        "/api/v1/messenger/link",
        json={"token": overflow_token},
    )

    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_webhook_insufficient_credit_returns_text_only_when_payments_disabled(
    client: TestClient,
    db_session: Session,
    captured_outgoing,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_linked_messenger_user(
        db_session,
        psid="psid-payments-disabled",
        page_id="page-payments-disabled",
        balance=0,
    )
    monkeypatch.setattr(settings, "payments_enabled", False)

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-payments-disabled",
                "time": 1700005000,
                "messaging": [
                    {
                        "sender": {"id": "psid-payments-disabled"},
                        "recipient": {"id": "page-payments-disabled"},
                        "timestamp": 1700005000,
                        "message": {
                            "mid": "m_payments_disabled",
                            "text": "請幫我分析",
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/messenger/webhook", json=payload)

    assert response.status_code == 200
    assert len(captured_outgoing) == 1
    _, outgoing = captured_outgoing[0]
    assert outgoing.kind == "text"
    assert outgoing.text == "體驗點數已用完，目前暫未開放購點。"


def test_persistent_menu_uses_balance_and_settings_entries() -> None:
    menu = build_default_persistent_menu()

    assert menu[0]["title"] == "查看剩餘點數"
    assert menu[0]["payload"] == "SHOW_BALANCE"
    assert menu[1]["title"] == "前往設定"
    assert menu[1]["payload"] == "OPEN_SETTINGS"


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
