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
    openai_api_key: str | None = None
    vector_store_id: str | None = None
    openai_manifest_path: str = "openai_integration/input_files_manifest.json"
    openai_ask_model: str = "gpt-5.2-2025-12-11"
    openai_ask_pipeline: Literal["one_stage", "two_stage"] = "one_stage"
    openai_ask_top_k: int = 3
    openai_ask_system_prompt: str = (
        "你是 ELIN 神域引擎問答助手，請根據提供檔案內容給出清楚可行的回答。"
        "回答格式以『結論 -> 必要說明』為主。"
        "answer_without_followup 必須只包含主回答正文，不可包含任何延伸問題、延伸問題前綴、"
        "或『如果你願意，我可以再幫你看看』之類的收尾句。"
        "followup_options 請產出 0 到 3 個可直接點擊送出的完整追問，"
        "每一個都要像使用者下一步會直接問你的完整問題。"
        "不要要求使用者先補資料、先做選擇、先告訴你某個欄位，"
        "也不要產生半句式選項或問卷式選項。"
        "followup_options 彼此必須明顯不同，且要延續同一題脈絡。"
    )
    messenger_enabled: bool = False
    meta_verify_token: str | None = None
    meta_page_access_token: str | None = None
    meta_app_secret: str | None = None
    messenger_verify_signature: bool = False
    messenger_outbound_mode: Literal["noop", "meta_graph"] = "noop"
    messenger_web_base_url: str = "http://localhost:3000"
    messenger_profile_sync_on_startup: bool = False
    payments_enabled: bool = True
    launch_credit_grant_amount: int = 50

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
