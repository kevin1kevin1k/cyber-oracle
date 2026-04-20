from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.openai_constants import (
    DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT,
    DEFAULT_OPENAI_ASK_SYSTEM_PROMPT,
    DEFAULT_OPENAI_FREE_ASK_SYSTEM_PROMPT,
    DEFAULT_OPENAI_FREE_FOLLOWUP_SYSTEM_PROMPT,
)


class Settings(BaseSettings):
    app_env: str = "dev"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/elin"
    jwt_secret: str = "dev-only-change-me-please-replace-32+"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60
    openai_api_key: str | None = None
    vector_store_id: str | None = None
    openai_manifest_path: str = "openai_integration/input_files_manifest.json"
    openai_ask_model: str = "gpt-5.2-2025-12-11"
    openai_ask_pipeline: Literal["one_stage", "two_stage"] = "one_stage"
    openai_ask_top_k: int = 3
    openai_ask_system_prompt: str = DEFAULT_OPENAI_ASK_SYSTEM_PROMPT
    openai_free_ask_system_prompt: str = DEFAULT_OPENAI_FREE_ASK_SYSTEM_PROMPT
    openai_free_followup_system_prompt: str = DEFAULT_OPENAI_FREE_FOLLOWUP_SYSTEM_PROMPT
    openai_ask_enable_compression: bool = False
    openai_ask_compression_system_prompt: str = DEFAULT_OPENAI_ASK_COMPRESSION_SYSTEM_PROMPT
    messenger_enabled: bool = False
    meta_verify_token: str | None = None
    meta_page_access_token: str | None = None
    meta_app_secret: str | None = None
    messenger_verify_signature: bool = False
    messenger_outbound_mode: Literal["noop", "meta_graph"] = "noop"
    messenger_send_timeout_seconds: float = 10.0
    messenger_send_max_attempts: int = 3
    messenger_send_initial_backoff_ms: int = 500
    messenger_web_base_url: str = "http://localhost:3000"
    messenger_profile_sync_on_startup: bool = False
    payments_enabled: bool = True
    launch_credit_grant_amount: int = 50

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    @model_validator(mode="after")
    def normalize_database_url(self) -> "Settings":
        database_url = self.database_url.strip()
        if database_url.startswith("postgres://"):
            self.database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]
        elif database_url.startswith("postgresql://") and "+psycopg" not in database_url:
            self.database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]
        else:
            self.database_url = database_url
        return self

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> "Settings":
        app_env = self.app_env.strip().lower()
        jwt_secret = self.jwt_secret.strip()
        default_secret = "dev-only-change-me-please-replace-32+"
        if app_env == "prod":
            if not jwt_secret:
                raise ValueError("JWT_SECRET must not be empty when APP_ENV=prod")
            if jwt_secret == default_secret:
                raise ValueError("JWT_SECRET must not use development default when APP_ENV=prod")
            if len(jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters when APP_ENV=prod")
        return self

    @model_validator(mode="after")
    def validate_messenger_settings(self) -> "Settings":
        app_env = self.app_env.strip().lower()
        if self.messenger_enabled and not (self.meta_verify_token or "").strip():
            raise ValueError("META_VERIFY_TOKEN is required when MESSENGER_ENABLED=true")

        if self.messenger_outbound_mode == "meta_graph":
            if not (self.meta_page_access_token or "").strip():
                raise ValueError(
                    "META_PAGE_ACCESS_TOKEN is required when MESSENGER_OUTBOUND_MODE=meta_graph"
                )
        if self.messenger_verify_signature and not (self.meta_app_secret or "").strip():
            raise ValueError("META_APP_SECRET is required when MESSENGER_VERIFY_SIGNATURE=true")
        if app_env == "prod" and self.messenger_enabled and not self.messenger_verify_signature:
            raise ValueError("MESSENGER_VERIFY_SIGNATURE must be true when APP_ENV=prod")
        if self.messenger_send_timeout_seconds <= 0:
            raise ValueError("MESSENGER_SEND_TIMEOUT_SECONDS must be > 0")
        if self.messenger_send_max_attempts < 1:
            raise ValueError("MESSENGER_SEND_MAX_ATTEMPTS must be >= 1")
        if self.messenger_send_initial_backoff_ms < 0:
            raise ValueError("MESSENGER_SEND_INITIAL_BACKOFF_MS must be >= 0")
        return self

    @model_validator(mode="after")
    def validate_launch_settings(self) -> "Settings":
        if self.launch_credit_grant_amount < 0:
            raise ValueError("LAUNCH_CREDIT_GRANT_AMOUNT must be >= 0")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
