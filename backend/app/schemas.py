from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    lang: Literal["zh", "vi"] = "zh"
    mode: Literal["analysis", "advice", "verdict", "oracle"] = "analysis"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be empty")
        return stripped


class LayerPercentage(BaseModel):
    label: Literal["主層", "輔層", "參照層"]
    pct: int


class FollowupOption(BaseModel):
    id: str
    content: str


class AskResponse(BaseModel):
    answer: str
    source: Literal["rag", "rule", "openai", "mock"]
    layer_percentages: list[LayerPercentage]
    request_id: str
    followup_options: list[FollowupOption]


class AskHistoryItem(BaseModel):
    question_id: str
    question_text: str
    answer_preview: str
    source: Literal["rag", "rule", "openai", "mock"]
    charged_credits: int
    created_at: datetime


class AskHistoryListResponse(BaseModel):
    items: list[AskHistoryItem]
    total: int


class ErrorResponse(BaseModel):
    code: Literal["UNAUTHORIZED", "EMAIL_NOT_VERIFIED", "INSUFFICIENT_CREDIT"]
    message: str


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)
    channel: str | None = Field(default=None, max_length=32)
    channel_user_id: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("invalid email format")
        return normalized


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    email_verified: bool
    verification_token: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("invalid email format")
        return normalized


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    email_verified: bool


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("token must not be empty")
        return token


class VerifyEmailResponse(BaseModel):
    status: Literal["verified"]


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("invalid email format")
        return normalized


class ForgotPasswordResponse(BaseModel):
    status: Literal["accepted"]
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=256)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("token must not be empty")
        return token


class ResetPasswordResponse(BaseModel):
    status: Literal["password_reset"]


class CreditBalanceResponse(BaseModel):
    balance: int
    updated_at: datetime | None


class CreditTransactionItem(BaseModel):
    id: str
    action: Literal["reserve", "capture", "refund", "grant", "purchase"]
    amount: int
    reason_code: str
    request_id: str
    question_id: str | None
    order_id: str | None
    created_at: datetime


class CreditTransactionListResponse(BaseModel):
    items: list[CreditTransactionItem]
    total: int


class CreateOrderRequest(BaseModel):
    package_size: Literal[1, 3, 5]
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        return key


class OrderResponse(BaseModel):
    id: str
    user_id: str
    package_size: Literal[1, 3, 5]
    amount_twd: Literal[168, 358, 518]
    status: Literal["pending", "paid", "failed", "refunded"]
    idempotency_key: str
    created_at: datetime
    paid_at: datetime | None


class SimulatePaidResponse(BaseModel):
    order: OrderResponse
    wallet_balance: int
