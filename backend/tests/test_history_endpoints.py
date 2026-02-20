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
        Followup.__table__,
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
        session.query(Followup).delete()
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


def _create_followup_link(
    db_session: Session,
    *,
    user_id,
    parent_question_id,
    child_question_id,
    content: str,
    created_at: datetime,
) -> Followup:
    followup = Followup(
        user_id=user_id,
        question_id=parent_question_id,
        content=content,
        origin_request_id=f"req-followup-{uuid.uuid4()}",
        status="used",
        used_question_id=child_question_id,
        used_at=created_at,
        created_at=created_at,
    )
    db_session.add(followup)
    return followup


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


def test_history_detail_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/history/questions/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_history_detail_returns_404_for_missing_or_foreign_question(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    other_user, _ = _create_user_with_token(db_session)
    now = datetime.now(UTC)
    foreign_question = _create_question_with_answer(
        db_session,
        user_id=other_user.id,
        question_text="其他人題目",
        answer_text="其他人答案",
        created_at=now,
        request_id="req-foreign",
        idempotency_key="k-foreign",
    )
    db_session.commit()

    missing = client.get(
        f"/api/v1/history/questions/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "QUESTION_NOT_FOUND"

    foreign = client.get(
        f"/api/v1/history/questions/{foreign_question.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "QUESTION_NOT_FOUND"
    assert user.id != other_user.id


def test_history_detail_returns_tree_and_transactions(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    now = datetime.now(UTC)

    root = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="主問題",
        answer_text="主回答完整內容",
        created_at=now - timedelta(minutes=3),
        request_id="req-root",
        idempotency_key="k-root",
    )
    child_a = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="延伸問題 A",
        answer_text="延伸回答 A",
        created_at=now - timedelta(minutes=2),
        request_id="req-child-a",
        idempotency_key="k-child-a",
    )
    child_b = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="延伸問題 B",
        answer_text="延伸回答 B",
        created_at=now - timedelta(minutes=1),
        request_id="req-child-b",
        idempotency_key="k-child-b",
    )
    _create_followup_link(
        db_session,
        user_id=user.id,
        parent_question_id=root.id,
        child_question_id=child_a.id,
        content="延伸按鈕 A",
        created_at=now - timedelta(minutes=2),
    )
    _create_followup_link(
        db_session,
        user_id=user.id,
        parent_question_id=child_a.id,
        child_question_id=child_b.id,
        content="延伸按鈕 B",
        created_at=now - timedelta(minutes=1),
    )
    db_session.add_all(
        [
            CreditTransaction(
                user_id=user.id,
                question_id=root.id,
                action="capture",
                amount=-1,
                reason_code="ASK_CAPTURED",
                idempotency_key="cap-root",
                request_id="req-cap-root",
                created_at=now - timedelta(minutes=3),
            ),
            CreditTransaction(
                user_id=user.id,
                question_id=child_a.id,
                action="capture",
                amount=-1,
                reason_code="ASK_CAPTURED",
                idempotency_key="cap-child-a",
                request_id="req-cap-child-a",
                created_at=now - timedelta(minutes=2),
            ),
            CreditTransaction(
                user_id=user.id,
                question_id=child_a.id,
                action="refund",
                amount=1,
                reason_code="ASK_REFUNDED",
                idempotency_key="refund-child-a",
                request_id="req-refund-child-a",
                created_at=now - timedelta(minutes=1),
            ),
            CreditTransaction(
                user_id=user.id,
                question_id=child_b.id,
                action="capture",
                amount=-1,
                reason_code="ASK_CAPTURED",
                idempotency_key="cap-child-b",
                request_id="req-cap-child-b",
                created_at=now - timedelta(seconds=30),
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/history/questions/{root.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["root"]["question_id"] == str(root.id)
    assert payload["root"]["question_text"] == "主問題"
    assert payload["root"]["answer_text"] == "主回答完整內容"
    assert payload["root"]["charged_credits"] == 1
    assert len(payload["root"]["children"]) == 1

    first_child = payload["root"]["children"][0]
    assert first_child["question_id"] == str(child_a.id)
    assert first_child["charged_credits"] == 1
    assert len(first_child["children"]) == 1
    assert first_child["children"][0]["question_id"] == str(child_b.id)
    assert first_child["children"][0]["charged_credits"] == 1

    actions = [tx["action"] for tx in payload["transactions"]]
    assert actions == ["capture", "capture", "refund", "capture"]


def test_history_list_excludes_followup_children(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    now = datetime.now(UTC)
    root = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="主題第一題",
        answer_text="主題第一題答案",
        created_at=now - timedelta(minutes=2),
        request_id="req-topic-root",
        idempotency_key="k-topic-root",
    )
    child = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="主題延伸題",
        answer_text="主題延伸答案",
        created_at=now - timedelta(minutes=1),
        request_id="req-topic-child",
        idempotency_key="k-topic-child",
    )
    _create_followup_link(
        db_session,
        user_id=user.id,
        parent_question_id=root.id,
        child_question_id=child.id,
        content="延伸按鈕",
        created_at=now - timedelta(minutes=1),
    )
    db_session.commit()

    response = client.get(
        "/api/v1/history/questions?limit=20&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["question_id"] == str(root.id)
    assert payload["items"][0]["question_text"] == "主題第一題"


def test_history_detail_with_child_id_returns_root_conversation(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    now = datetime.now(UTC)
    root = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="根問題",
        answer_text="根回答",
        created_at=now - timedelta(minutes=2),
        request_id="req-root-conv",
        idempotency_key="k-root-conv",
    )
    child = _create_question_with_answer(
        db_session,
        user_id=user.id,
        question_text="子問題",
        answer_text="子回答",
        created_at=now - timedelta(minutes=1),
        request_id="req-child-conv",
        idempotency_key="k-child-conv",
    )
    _create_followup_link(
        db_session,
        user_id=user.id,
        parent_question_id=root.id,
        child_question_id=child.id,
        content="延伸",
        created_at=now - timedelta(minutes=1),
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/history/questions/{child.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["root"]["question_id"] == str(root.id)
    assert len(payload["root"]["children"]) == 1
    assert payload["root"]["children"][0]["question_id"] == str(child.id)
