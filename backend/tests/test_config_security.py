import pytest
from pydantic import ValidationError

from app.config import Settings


def test_prod_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="development default"):
        Settings(app_env="prod", jwt_secret="dev-only-change-me-please-replace-32+")


def test_prod_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(app_env="prod", jwt_secret="short-secret")


def test_prod_accepts_strong_jwt_secret_without_email_settings() -> None:
    settings = Settings(
        _env_file=None,
        app_env="prod",
        jwt_secret="prod-very-strong-secret-01234567890123456789",
        messenger_enabled=False,
    )

    assert settings.app_env == "prod"


def test_database_url_normalizes_render_postgresql_connection_string() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@host:5432/elin",
    )

    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/elin"


def test_database_url_normalizes_legacy_postgres_scheme() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgres://user:pass@host:5432/elin",
    )

    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/elin"


def test_database_url_keeps_explicit_psycopg_scheme() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@host:5432/elin",
    )

    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/elin"


def test_dev_allows_default_jwt_secret() -> None:
    settings = Settings(app_env="dev", jwt_secret="dev-only-change-me-please-replace-32+")

    assert settings.app_env == "dev"


def test_messenger_enabled_requires_verify_token() -> None:
    with pytest.raises(ValidationError, match="META_VERIFY_TOKEN is required"):
        Settings(messenger_enabled=True, meta_verify_token="")


def test_messenger_meta_graph_requires_page_access_token() -> None:
    with pytest.raises(ValidationError, match="META_PAGE_ACCESS_TOKEN is required"):
        Settings(
            messenger_outbound_mode="meta_graph",
            meta_page_access_token="",
        )


def test_prod_messenger_requires_signature_verification() -> None:
    with pytest.raises(ValidationError, match="MESSENGER_VERIFY_SIGNATURE must be true"):
        Settings(
            app_env="prod",
            jwt_secret="prod-very-strong-secret-01234567890123456789",
            messenger_enabled=True,
            meta_verify_token="verify-token",
            messenger_verify_signature=False,
        )
