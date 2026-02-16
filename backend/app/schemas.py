from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class AskResponse(BaseModel):
    answer: str
    source: Literal["mock"]
    layer_percentages: list[LayerPercentage]
    request_id: str


class ErrorResponse(BaseModel):
    code: Literal["UNAUTHORIZED", "EMAIL_NOT_VERIFIED"]
    message: str
