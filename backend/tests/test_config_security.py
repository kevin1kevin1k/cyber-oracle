import pytest
from pydantic import ValidationError

from app.config import Settings
from app.openai_constants import (
    DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT,
    DEFAULT_OPENAI_ASK_SYSTEM_PROMPT,
    DEFAULT_OPENAI_FREE_ASK_SYSTEM_PROMPT,
    DEFAULT_OPENAI_FREE_FOLLOWUP_SYSTEM_PROMPT,
)


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


def test_messenger_send_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="MESSENGER_SEND_TIMEOUT_SECONDS must be > 0"):
        Settings(messenger_send_timeout_seconds=0)


def test_messenger_send_attempts_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError, match="MESSENGER_SEND_MAX_ATTEMPTS must be >= 1"):
        Settings(messenger_send_max_attempts=0)


def test_openai_compression_settings_are_configurable() -> None:
    settings = Settings(
        _env_file=None,
        openai_ask_enable_compression=True,
        openai_ask_compression_system_prompt="compression prompt",
    )

    assert settings.openai_ask_enable_compression is True
    assert settings.openai_ask_compression_system_prompt == "compression prompt"


def test_openai_default_prompts_are_loaded_from_constants() -> None:
    settings = Settings(_env_file=None)

    assert settings.openai_ask_system_prompt == DEFAULT_OPENAI_ASK_SYSTEM_PROMPT
    assert settings.openai_free_ask_system_prompt == DEFAULT_OPENAI_FREE_ASK_SYSTEM_PROMPT
    assert settings.openai_free_followup_system_prompt == DEFAULT_OPENAI_FREE_FOLLOWUP_SYSTEM_PROMPT
    assert (
        settings.openai_ask_compression_system_prompt
        == DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT
    )


def test_openai_compression_prompt_contains_new_style_constraints() -> None:
    prompt = DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT

    assert "不可同時給多個方向" in prompt
    assert "不可先講「如果你是 A，就 B；如果你是 C，就 D」" in prompt
    assert "2️⃣ 第一層｜核心本質" in prompt
    assert "5️⃣ 第四層｜風險與代價" in prompt
    assert "不可把 followup_options 寫進主回答正文" in prompt


def test_openai_compression_prompt_contains_few_shot_examples_and_guardrails() -> None:
    prompt = DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT

    assert "以下提供同一題的壞例子與好例子，作為風格參考" in prompt
    assert "壞例子（應避免）" in prompt
    assert "好例子（應靠近）" in prompt
    assert "你現在該上的不是說服課，是表達課" in prompt
    assert "如果你現在最需要的是把想法講清楚" in prompt
    assert "這些例子只是風格參考，不是你這次的輸出格式" in prompt
    assert "你實際輸出時仍必須嚴格遵守既有 JSON schema" in prompt
