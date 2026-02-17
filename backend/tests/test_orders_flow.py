import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
        pytest.skip("Refusing to run order tests on primary database 'elin'.")


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


def test_create_order_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/orders",
        json={"package_size": 1, "idempotency_key": "k1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_create_order_success_and_idempotent_replay(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)

    first = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 3, "idempotency_key": "order-k-1"},
    )
    assert first.status_code == 201
    first_payload = first.json()
    assert first_payload["package_size"] == 3
    assert first_payload["amount_twd"] == 358
    assert first_payload["status"] == "pending"

    second = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 3, "idempotency_key": "order-k-1"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_payload["id"]

    order_count = db_session.scalar(select(func.count(Order.id)).where(Order.user_id == user.id))
    assert order_count == 1


def test_simulate_paid_marks_order_paid_and_grants_credit(
    client: TestClient,
    db_session: Session,
) -> None:
    user, token = _create_user_with_token(db_session)
    create = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 5, "idempotency_key": "order-k-2"},
    )
    order_id = create.json()["id"]

    first_paid = client.post(
        f"/api/v1/orders/{order_id}/simulate-paid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_paid.status_code == 200
    payload = first_paid.json()
    assert payload["order"]["status"] == "paid"
    assert payload["wallet_balance"] == 5

    second_paid = client.post(
        f"/api/v1/orders/{order_id}/simulate-paid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_paid.status_code == 200
    payload2 = second_paid.json()
    assert payload2["wallet_balance"] == 5

    purchase_count = db_session.scalar(
        select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == user.id,
            CreditTransaction.action == "purchase",
            CreditTransaction.order_id == uuid.UUID(order_id),
        )
    )
    assert purchase_count == 1


def test_simulate_paid_rejects_in_production(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, token = _create_user_with_token(db_session)
    create = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 1, "idempotency_key": "order-k-3"},
    )
    order_id = create.json()["id"]

    monkeypatch.setattr(settings, "app_env", "prod")
    denied = client.post(
        f"/api/v1/orders/{order_id}/simulate-paid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "FORBIDDEN_IN_PRODUCTION"


def test_simulate_paid_returns_404_for_other_user_order(
    client: TestClient,
    db_session: Session,
) -> None:
    _, owner_token = _create_user_with_token(db_session)
    _, other_token = _create_user_with_token(db_session)

    create = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"package_size": 1, "idempotency_key": "owner-order"},
    )
    order_id = create.json()["id"]

    not_found = client.post(
        f"/api/v1/orders/{order_id}/simulate-paid",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert not_found.status_code == 404
    assert not_found.json()["detail"]["code"] == "ORDER_NOT_FOUND"


def test_simulate_paid_rejects_non_pending_status(client: TestClient, db_session: Session) -> None:
    user, token = _create_user_with_token(db_session)
    create = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 1, "idempotency_key": "order-k-4"},
    )
    order_id = create.json()["id"]

    order = db_session.scalar(
        select(Order).where(Order.id == uuid.UUID(order_id), Order.user_id == user.id)
    )
    assert order is not None
    order.status = "failed"
    db_session.add(order)
    db_session.commit()

    response = client.post(
        f"/api/v1/orders/{order_id}/simulate-paid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_STATUS_INVALID_FOR_PAYMENT"


def test_simulate_paid_concurrent_first_payment_is_idempotent(
    engine,
    client: TestClient,
    db_session: Session,
) -> None:
    _, token = _create_user_with_token(db_session)
    create = client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_size": 3, "idempotency_key": "order-k-concurrent"},
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as threaded_client:
            def _call_simulate() -> int:
                response = threaded_client.post(
                    f"/api/v1/orders/{order_id}/simulate-paid",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return response.status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(lambda _: _call_simulate(), range(2)))
    finally:
        app.dependency_overrides.clear()

    assert statuses == [200, 200]

    order = db_session.scalar(select(Order).where(Order.id == uuid.UUID(order_id)))
    assert order is not None
    assert order.status == "paid"

    wallet = db_session.scalar(select(CreditWallet).where(CreditWallet.user_id == order.user_id))
    assert wallet is not None
    assert wallet.balance == 3

    purchase_count = db_session.scalar(
        select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == order.user_id,
            CreditTransaction.action == "purchase",
            CreditTransaction.order_id == order.id,
        )
    )
    assert purchase_count == 1
