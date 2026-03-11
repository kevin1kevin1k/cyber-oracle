import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.messenger_identity import MessengerIdentity
from app.models.user import User

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run messenger identity tests on primary database 'elin'.")


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


def test_create_and_lookup_identity_without_linked_user(db_session: Session) -> None:
    identity = MessengerIdentity(platform="messenger", psid="psid-1", page_id="page-1")
    db_session.add(identity)
    db_session.commit()

    found = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.platform == "messenger",
            MessengerIdentity.psid == "psid-1",
            MessengerIdentity.page_id == "page-1",
        )
    )
    assert found is not None
    assert found.user_id is None
    assert found.status == "unlinked"
    assert found.is_active is True


def test_unique_platform_psid_page_id(db_session: Session) -> None:
    first = MessengerIdentity(platform="messenger", psid="psid-dup", page_id="page-dup")
    db_session.add(first)
    db_session.commit()

    second = MessengerIdentity(platform="messenger", psid="psid-dup", page_id="page-dup")
    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_linked_identity_can_point_to_internal_user(db_session: Session) -> None:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    identity = MessengerIdentity(
        platform="messenger",
        psid="psid-linked",
        page_id="",
        user_id=user.id,
        status="linked",
    )
    db_session.add(identity)
    db_session.commit()

    found = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-linked",
            MessengerIdentity.page_id == "",
        )
    )
    assert found is not None
    assert found.user_id == user.id
    assert found.status == "linked"


def test_last_interacted_at_can_be_updated(db_session: Session) -> None:
    identity = MessengerIdentity(platform="messenger", psid="psid-last", page_id="page-last")
    db_session.add(identity)
    db_session.commit()

    expected = datetime.now(UTC)
    identity.last_interacted_at = expected
    db_session.add(identity)
    db_session.commit()

    found = db_session.scalar(
        select(MessengerIdentity).where(
            MessengerIdentity.psid == "psid-last",
            MessengerIdentity.page_id == "page-last",
        )
    )
    assert found is not None
    assert found.last_interacted_at is not None
