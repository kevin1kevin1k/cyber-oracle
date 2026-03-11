from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/elin"
    jwt_secret: str = "dev-only-change-me-please-replace-32+"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60
    openai_manifest_path: str = "openai_integration/input_files_manifest.json"
    openai_ask_model: str = "gpt-5.2-2025-12-11"
    openai_ask_pipeline: Literal["one_stage", "two_stage"] = "one_stage"
    openai_ask_top_k: int = 3
    openai_ask_system_prompt: str = (
        "你是 ELIN 神域引擎問答助手，請根據提供檔案內容給出清楚可行的回答。"
    )
    messenger_enabled: bool = False
    meta_verify_token: str | None = None
    meta_page_access_token: str | None = None
    meta_app_secret: str | None = None
    messenger_verify_signature: bool = False
    messenger_outbound_mode: Literal["noop", "meta_graph"] = "noop"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

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
        if self.messenger_enabled and not (self.meta_verify_token or "").strip():
            raise ValueError("META_VERIFY_TOKEN is required when MESSENGER_ENABLED=true")

        if self.messenger_outbound_mode == "meta_graph":
            if not (self.meta_page_access_token or "").strip():
                raise ValueError(
                    "META_PAGE_ACCESS_TOKEN is required when MESSENGER_OUTBOUND_MODE=meta_graph"
                )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
