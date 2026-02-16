import os
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.user import User


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/elin_test",
)


def _ensure_safe_test_database(url: str) -> None:
    db_name = make_url(url).database
    if db_name == "elin":
        pytest.skip("Refusing to run destructive schema tests on primary database 'elin'.")


@pytest.fixture(scope="module")
def engine():
    _ensure_safe_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(f"PostgreSQL is not available at {TEST_DATABASE_URL}")

    Base.metadata.drop_all(bind=engine, tables=[User.__table__])
    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    yield engine
    Base.metadata.drop_all(bind=engine, tables=[User.__table__])
    engine.dispose()


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_create_user_defaults(db_session) -> None:
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        password_hash="hashed-password",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.email_verified is False
    assert user.created_at is not None
    assert user.updated_at is not None


def test_email_unique_constraint(db_session) -> None:
    db_session.add(
        User(
            id=uuid.uuid4(),
            email="dup@example.com",
            password_hash="pw1",
        )
    )
    db_session.commit()

    db_session.add(
        User(
            id=uuid.uuid4(),
            email="dup@example.com",
            password_hash="pw2",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_channel_identity_unique_constraint(db_session) -> None:
    db_session.add(
        User(
            id=uuid.uuid4(),
            email="fb1@example.com",
            password_hash="pw1",
            channel="facebook",
            channel_user_id="123",
        )
    )
    db_session.commit()

    db_session.add(
        User(
            id=uuid.uuid4(),
            email="fb2@example.com",
            password_hash="pw2",
            channel="facebook",
            channel_user_id="123",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
